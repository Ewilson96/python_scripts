#!/usr/bin/env python3
"""
Ennil Wilson
Server health check script — modular refactor.

Modules (as functions grouped by responsibility):
  config        — all static data (servers, credentials, commands)
  connectivity  — ping / reachability logic
  ssh_runner    — SSH connection and command execution
  reporter      — all print/display logic
  main          — orchestration only
"""

import subprocess
import paramiko
from datetime import datetime
import json
import csv
from pathlib import Path


# ─── CONFIG ──────────────────────────────────────────────────────────────────
#
# Why its own section?
#   Every "what do I check" or "who do I connect as" decision lives here.
#   To add a new server or swap a command you touch exactly one place,
#   and you never have to read SSH or printing code to do it.
#
# The key design choice: a dict-of-dicts maps each hostname to its metadata
# rather than scattering parallel lists and if/elif chains throughout the code.

PORT = 22
KEY_PATH = "/home/ewilson/.ssh/id_ed25519"
LOG_DIR = Path("/home/ewilson/home_lab/scripts/logs")

# One entry per host.  Add "dbserver" here and it works everywhere automatically.
SERVERS = {
    "pve":    {"username": "labadmin"},
    "ubuntu": {"username": "ewilson"},
    "alma":   {"username": "ewilson"},
}

# Commands every host runs.
GENERAL_CMDS = {
    "hostname":   "hostname",
    "ip_address": "hostname -I",
    "uptime":     "uptime",
    "os_version": "uname -r",
    "disk":       "df -h /",
    "memory":     "free -m",
    "date":       "date",
}

# Commands keyed by hostname — only merged in for that host.
HOST_CMDS = {
    "pve": {
        "proxy_status":     "systemctl is-active pveproxy",
        "pvedaemon_status": "systemctl is-active pvedaemon",
        "cluster_status":   "systemctl is-active pve-cluster",
        "failed_services":  "systemctl --failed --no-pager",
        "error_logs":       "journalctl -p err -n 20 --no-pager",
        "upgradable":       "apt list --upgradable 2>/dev/null",
    },
    "ubuntu": {
        "cockpit_status": "systemctl is-active cockpit.socket",
        "port_status": "ss -tulpn | grep ':9090' | awk '{print $2}'",
        #last wg handshake 
        "wiregaurd_hs": "date -d @$(sudo -n /usr/bin/wg show wg0 latest-handshakes | awk '{print $2}')",
        "vpn_intf": "if ip -brief addr show wg0 | grep -q '10.0.0.1/24'; then     echo 'interface is enabled!'; else     echo 'interface is disabled!'; fi",
        "ddns_status": "duckdns=$(dig +short ewilso73homelab.duckdns.org); public_v4=$(curl -4 -s ifconfig.me); if [[ \"$duckdns\" == \"$public_v4\" ]]; then echo 'service is up!'; else echo 'service is down!'; fi",
        "upgradable":     "apt list --upgradable 2>/dev/null",
    },
    "alma": {
        "ssh_status": "systemctl is-active sshd",
        "fw_status":  "systemctl is-active firewalld",
        "upgradable": "dnf check-update 2>/dev/null",
    },
}

# Maps each host to its package manager's update command.
# Separated from HOST_CMDS because this command is only run on-demand
# after user confirmation — it's an action, not a read-only query.
UPDATE_CMD = {
    "pve":    "sudo apt-get update -y && sudo apt-get upgrade -y",
    "ubuntu": "sudo apt-get update -y && sudo apt-get upgrade -y",
    "alma":   "sudo dnf upgrade -y",
}


# ─── CONNECTIVITY ────────────────────────────────────────────────────────────
#
# Why separate from SSH?
#   Ping and SSH are two different failure modes.  Keeping them apart lets you
#   test ping logic without spinning up a real SSH server, and makes it trivial
#   to swap the reachability check (e.g. TCP probe instead of ICMP) later.

def ping_host(hostname: str) -> bool:
    """Return True if the host responds to a single ping within 1 second."""
    result = subprocess.run(
        ["ping", "-c", "1", "-W", "1", hostname],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def get_reachable(servers: dict) -> list[str]:
    """
    Ping every server; print a notice for unreachable ones.
    Returns a list of reachable hostnames in the original order.
    """
    reachable = []
    for host in servers:
        if ping_host(host):
            reachable.append(host)
        else:
            print(f"{host} is down.")
    return reachable


# ─── SSH RUNNER ──────────────────────────────────────────────────────────────
#
# Why split connecting from running commands?
#   get_ssh_client() has one job: give you an open, authenticated client.
#   run_commands() has one job: execute a dict of commands and return results.
#   If auth ever needs to change (certificate, jump host, etc.) you fix
#   get_ssh_client() and nothing else changes.

def get_ssh_client(hostname: str, username: str) -> paramiko.SSHClient:
    """Open and return an authenticated SSH client.  Caller must close it."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname,
        port=PORT,
        username=username,
        key_filename=KEY_PATH,
        timeout=5,
    )
    return client


def run_commands(client: paramiko.SSHClient, commands: dict) -> dict:
    """
    Execute each command in `commands` over an open SSH client.
    Returns a dict with the same keys and stdout/error strings as values.

    Why return a dict instead of printing?
      The caller decides what to do with results — print, write to a file,
      compare against thresholds, feed into an alert.  This function stays
      ignorant of all that.
    """
    results = {}
    for key, cmd in commands.items():
        _, stdout, stderr = client.exec_command(cmd)
        output = stdout.read().decode().strip()
        error  = stderr.read().decode().strip()
        results[key] = output if output else f"[no output: {error}]"
    return results


def has_updates(upgradable_output: str, hostname: str) -> bool:
    """
    Determine whether the upgradable command returned real packages.

    Why a dedicated function?
      apt and dnf have different output formats and different "nothing to do"
      signals.  Centralising the check means the caller just asks a yes/no
      question and never has to know about either format.

    apt:  always prints a "Listing..." header line.  Real packages appear on
          subsequent lines.  So >1 line means updates exist.
    dnf:  prints nothing (or only warnings) when up to date.  Any non-empty
          output after stripping means updates exist.
    """
    lines = [l for l in upgradable_output.splitlines() if l.strip()]

    if hostname == "alma":
        # dnf check-update: non-empty output means packages are available.
        # It exits with code 100 when updates exist, but exec_command doesn't
        # surface exit codes easily, so we read the output instead.
        return len(lines) > 0
    else:
        # apt: first line is always "Listing..." — skip it.
        # If there's at least one more line, real packages are listed.
        return len(lines) > 1


def prompt_and_update(hostname: str, upgradable_output: str) -> None:
    """
    Show the user what's upgradable on a host, ask Y/N, then run the
    appropriate update command over a fresh SSH connection if confirmed.

    The flow:
      1. Check whether there's anything to update (has_updates).
      2. Print the upgradable list so the user can see what they're approving.
      3. Ask locally — input() blocks your terminal, nothing happens remotely.
      4. On 'y': open SSH again, run the update command, stream output live.
      5. On anything else: skip silently.

    Why open a second SSH connection instead of reusing the first?
      collect_host_data() already closed its client by the time we get here
      (the finally block in that function guarantees it).  Opening a fresh
      client is cleaner than passing a long-lived client object around, and
      update runs are infrequent enough that the reconnect cost doesn't matter.

    Why stream output line-by-line instead of capturing it?
      apt/dnf update can take a while.  Buffering all output and printing at
      the end would make it look frozen.  Reading stdout as it arrives gives
      the user live feedback.
    """
    if not has_updates(upgradable_output, hostname):
        print(f"  {hostname}: currently up to date.\n")
        return

    print(f"{'─' * 40}")
    #       ────────────────────────────────────────
    print(f"       Upgradable packages on {hostname}:")
    print(f"{'─' * 40}")
    print(upgradable_output)

    answer = input(f"\n  Run update on {hostname}? [y/N]: ").strip().lower()

    if answer != "y":
        print(f"  Skipping update on {hostname}.")
        return

    cmd = UPDATE_CMD[hostname]
    username = SERVERS[hostname]["username"]
    print(f"\n      Running: {cmd}")
    print(f"{'─' * 40}")

    client = None
    try:
        client = get_ssh_client(hostname, username)
        _, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=90)
        # get_pty=True allocates a pseudo-terminal on the remote side.
        # This matters for sudo and for apt/dnf's progress output —
        # some programs buffer differently without a TTY attached.

        # Stream stdout line-by-line so the user sees progress live.
        for line in stdout:
            print(f"  {line}", end="")

        err = stderr.read().decode().strip()
        if err:
            print(f"\n  [stderr]: {err}")

        print(f"\n  Update complete on {hostname}.")

    except Exception as exc:
        print(f"  Update failed on {hostname}: {exc}")
    finally:
        if client:
            client.close()


def collect_host_data(hostname: str) -> dict | None:
    """
    Convenience wrapper: open SSH, run general + host-specific commands,
    close SSH, return the merged results dict.  Returns None on error.

    Why a wrapper?
      main() shouldn't have to know about merging command dicts or managing
      SSH client lifecycle.  One call → one result dict → done.
    """
    cfg = SERVERS[hostname]
    cmds = {**GENERAL_CMDS, **HOST_CMDS.get(hostname, {})}
    #cmds_json = json.dumps(cmds)

    client = None
    try:
        client = get_ssh_client(hostname, cfg["username"])
        return run_commands(client, cmds)
    except Exception as exc:
        print(f"Error connecting to {hostname}: {exc}")
        return None
    finally:
        # `finally` runs even if an exception was raised, so the client
        # is always closed — no resource leak even on partial failure.
        if client:
            client.close()


# ─── REPORTER ────────────────────────────────────────────────────────────────
#
# Why isolate all print() calls here?
#   If you ever want JSON output, a log file, or a Slack webhook, you only
#   change this section.  The data-gathering code doesn't move at all.

def print_summary(reachable: list, total: int) -> None:
    now = datetime.now()
    print(f"\nTimestamp: {now:%Y-%m-%d %H:%M:%S} EST")
    print(f"\n      *** Reachable VMs: {len(reachable)}/{total} ***\n")


def print_host(hostname: str, results: dict) -> None:
    """Print the formatted report for one host."""
    print("=" * 40)
           #========================================
    print(f"{'              HOST: ' + hostname.upper():^20}")
    #print(f"HOST: {hostname.upper():^20}")
    print("=" * 40)
    print(f"\nServer Date: {results['date']}")
    print(f"Hostname:    {results['hostname']}")
    print(f"IP Address:  {results['ip_address']}")
    print(f"Uptime:      {results['uptime']}")
    print(f"OS Version:  {results['os_version']}")
    print(f"\nDisk Usage:\n{results['disk']}")
    print(f"\nMemory:\n{results['memory']}")

    # Host-specific sections — each check is isolated so adding a new host
    # only requires adding an elif here and an entry in HOST_CMDS above.
    if hostname == "pve":
        _print_pve_section(hostname, results)
    elif hostname == "ubuntu":
        _print_ubuntu_section(results)
    elif hostname == "alma":
        _print_alma_section(results)

    print("\n")


def _print_pve_section(hostname: str, results: dict) -> None:
              #========================================
    print(f"\n            15 PVE Services")
    print("=" * 40)
    print(f"PVE Proxy:   {results['proxy_status']}")
    print(f"PVE Daemon:  {results['pvedaemon_status']}")
    print(f"PVE Cluster: {results['cluster_status']}")
    print(f"\n      HOST:systemctl failed services")
    print("-" * 40)
    print(results["failed_services"])
    print(f"\n     HOST: journalctl recent errors")
           #   ----------------------------------------
    print("-" * 40)
    print(results["error_logs"])


def _print_ubuntu_section(results: dict) -> None:
    print(f"\n             Ubuntu Services")
    print("=" * 40)
    print(f"VPN status:  {results['vpn_intf']}\nLast WG handshake/check-in: {results['wiregaurd_hs']}")
    print(f"DDNS status:  {results['ddns_status']}")
    print(f"cockpit.socket status: {results['cockpit_status']}")
    print(f"cockpit.socket port:   {results['port_status']}ING port 9090")


def _print_alma_section(results: dict) -> None:
    print(f"\n             Alma Services")
    #         ========================================
    print("=" * 40)
    print(f"SSH daemon:      {results['ssh_status']}")
    print(f"Firewalld:       {results['fw_status']}")

def log_engine(results: dict, hostname: str, reachable: int, total: int) -> None:
    filename = LOG_DIR/f"{datetime.now():%Y%m%d-%H%M%S}_{hostname}_status.csv"  

    with open(filename, "w") as f:
        f.write(f"Available Machines: {reachable}/{total}\n")
        f.write(f"Hostname: {results['hostname']}\n")
        f.write("-" * 40 + "\n")
        
        for key, value in results.items():
            f.write(f"{key}: {value}\n")
        
# ─── MAIN ────────────────────────────────────────────────────────────────────
#
# main() should read like a table of contents — high-level steps only.
# No SSH logic, no print formatting, no ping details.  Just orchestration.
#
# The `if __name__ == "__main__"` guard is a Python best practice:
# it lets another script import your functions without triggering a full run.

def main() -> None:
    reachable = get_reachable(SERVERS) 
    print_summary(reachable, len(SERVERS))

    # Phase 1: collect and display data for all hosts first.
    # We store results so Phase 2 can use them without re-running SSH queries.
    all_results = {}
    for host in reachable:
        results = collect_host_data(host)
        if results:
            all_results[host] = results
            print_host(host, results)
            log_engine(results,host,len(reachable),len(SERVERS))
    
    # Phase 2: after the full report, prompt for updates host-by-host.
    # Doing this after Phase 1 means the user sees the complete health picture
    # before making any update decisions — not interrupted mid-report.
    print("=" * 40)
    print("           Application Checks")
    print("=" * 40)
    for host, results in all_results.items():
        if "upgradable" in results:
            prompt_and_update(host, results["upgradable"])
    
if __name__ == "__main__":
    main()
