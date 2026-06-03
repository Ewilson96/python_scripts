#!/usr/bin/env python3
import subprocess
import paramiko
from datetime import datetime

port = 22
user_account = "ewilson"
password = "14971987"
lab_controller = "labadmin"

servers = ["pve", "ubuntu", "alma"]

general_cmds = {
    "hostname": "hostname",
    "ip_address": "hostname -I",
    "uptime": "uptime",
    "os_version": "uname -r",
    "disk": "df -h /",
    "memory": "free -m",
    "date": "date"
}

alma_cmds = {
    "ssh_status":"systemctl is-active sshd",
    "fw_status":"systemctl is-active firewalld"
}

ubuntu_cmds = {
    "cockpit_status": "systemctl is-active cockpit.socket",
    "port_status": "ss -tulpn | grep ':9090' | awk '{print $2}'"
}

controller_cmds = {
    "proxy_status": "systemctl is-active pveproxy",
    "pvedaemon_status": "systemctl is-active pvedaemon",
    "cluster_status": "systemctl is-active pve-cluster",
    "failed_services": "systemctl --failed --no-pager",
    "error_logs": "journalctl -p err -n 20 --no-pager"
}

now = datetime.now()
print("\n")
print(f"Timestamp: {now:%Y-%m-%d %H:%M:%S} EST")

def ping_helper(servers):
    ping_cmd = ["ping","-c","1","-W","1",servers]
    ping_result = subprocess.run(ping_cmd,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return ping_result.returncode == 0

reachable_servers = []

for i in servers:
    if ping_helper(i):
        reachable_servers.append(i)
        #print(f"{i} is up.")
    else:
        print(f"{i} is down.")

print(f"\n*** Reachable VMs: {len(reachable_servers)}/{len(servers)} ***\n")      

for i in reachable_servers:  
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        if i in ["ubuntu", "alma"]:
            username = user_account
        elif i == "pve":
            username = lab_controller
      
        ssh.connect(
            i,
            port=port,
            username=username,
            password=password,
            timeout=5
        )

        all_commands = general_cmds.copy()

        if i == "pve":
            all_commands.update(controller_cmds)
        elif i == "ubuntu":
            all_commands.update(ubuntu_cmds)
        elif i == "alma":
            all_commands.update(alma_cmds)

        results = {}

        for key, cmd in all_commands.items():
            stdin, stdout, stderr = ssh.exec_command(cmd)

            output = stdout.read().decode("utf-8").strip()
            error = stderr.read().decode("utf-8").strip()

            results[key] = output if output else f"Invalid SSH Response: {error}"
        
        print("=" * 40)
        print(f"HOST: {i}")
        print("=" * 40)
        print(f"\nServer Date: {results['date']}")
        print(f"Hostname: {results['hostname']}")
        print(f"IP Address: {results['ip_address']}")
        print(f"Uptime: {results['uptime']}")
        print(f"OS Version: {results['os_version']}")
        print(f"\nDisk Usage:\n{results['disk']}")
        print(f"\nMemory:\n{results['memory']}")
        
        if i == "pve":
            print(f"\nPVE Services")
            print("=" * 40)
            print(f"PVE Proxy: {results['proxy_status']}")
            print(f"PVE Daemon: {results['pvedaemon_status']}")
            print(f"PVE Cluster: {results['cluster_status']}")

            print(f"\nHOST: {i} - systemctl failed services")
            print("-" * 40)
            print(results["failed_services"])

            print(f"\nHOST: {i} - journalctl recent error logs")
            print("-" * 40)
            print(results["error_logs"])

        if i == "ubuntu":
            print(f"\nUbuntu Services")
            print("=" * 40)
            print(f"Remote Access - Service Status: {results['cockpit_status']}")
            print(f"Remote Access - Port Status: {results['port_status']}")

        if i == "alma":
            print(f"\nAlma Services")
            print("=" * 40)
            print(f"SSH daemon: {results['ssh_status']}")
            print(f"Firewalld daemon: {results['fw_status']}")
        print("\n")

    except Exception as e:
        print(f"Error for {i}: {e}")

    finally:
        ssh.close()
