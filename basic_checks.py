#!/usr/bin/env python3

import paramiko
from datetime import datetime

port = 22
user_account = "ewilson"
password = "14971987"
lab_controller = "labadmin"

servers = ["pve", "ubuntu", "alma"]

commands = {
    "uptime": "uptime",
    "disk": "df -h",
    "memory": "free -m",
    "hostname": "hostname",
    "date": "date"
}

now = datetime.now()
print(f"Timestamp: {now:%Y-%m-%d %H:%M:%S} EST")

for server in servers:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        if server in ["ubuntu", "alma"]:
            username = user_account
        elif server == "pve":
            username = lab_controller
        else:
            print(f"Unknown server: {server}")
            continue

        ssh.connect(
            server,
            port=port,
            username=username,
            password=password,
            timeout=5
        )

        results = {}

        for key, cmd in commands.items():
            stdin, stdout, stderr = ssh.exec_command(cmd)

            output = stdout.read().decode("utf-8").strip()
            error = stderr.read().decode("utf-8").strip()

            if error:
                results[key] = f"ERROR: {error}"
            else:
                results[key] = output

        print("=" * 40)
        print(f"HOST: {server}")
        print("=" * 40)
        print(f"Hostname:\n{results['hostname']}")
        print(f"\nUptime:\n{results['uptime']}")
        print(f"\nDisk Usage:\n{results['disk']}")
        print(f"\nMemory:\n{results['memory']}")
        print(f"\nServer Date:\n{results['date']}")
        print()

    except Exception as e:
        print(f"Error for {server}: {e}")

    finally:
        ssh.close()