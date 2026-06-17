import os
import requests

API_URL = "http://127.0.0.1:8000"
API_KEY = os.environ["API_KEY"]          # same key the server was started with

# Define your fleet of targets here (later: load from a file / inventory)
TARGETS = [
    {"host": "10.137.65.110", "username": "ubuntu", "password": "12345"},
    # add more targets here...
]

# Read-only checks to run on every target
READ_COMMANDS = [
    "uname -a",
    "uptime",
    "df -h /",
]

# Config changes to apply on every target (go through /configure -> sudo)
CONFIG_COMMANDS = [
    "bash -c \"echo 'Managed by automation' > /etc/motd\"",
    # "timedatectl set-timezone Asia/Dhaka",
]


def call(endpoint, target, command):
    resp = requests.post(
        f"{API_URL}/{endpoint}",
        headers={"X-API-Key": API_KEY},
        json={**target, "command": command},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def main():
    for target in TARGETS:
        host = target["host"]
        print(f"\n=== {host} ===")

        # 1. Read first (verify reachability + current state)
        for cmd in READ_COMMANDS:
            r = call("run", target, cmd)
            print(f"[read] {cmd}\n{r['stdout'].strip()}")

        # 2. Apply config changes
        for cmd in CONFIG_COMMANDS:
            r = call("configure", target, cmd)
            status = "ok" if r["exit_code"] == 0 else f"FAILED ({r['exit_code']})"
            print(f"[config] {cmd} -> {status}")


if __name__ == "__main__":
    main()