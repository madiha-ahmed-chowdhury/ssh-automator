# SSH Automation PoC

A proof-of-concept that connects to a remote machine over SSH, runs commands,
returns their output, and exposes this through a FastAPI service. Built and
tested against a local Multipass Ubuntu VM as a stand-in target.

> **Note on the real router:** This PoC targets an Ubuntu VM, not the MikroTik
> at `10.20.230.111`. That router is on a different, firewalled network
> (`10.20.x` vs the laptop's `10.19.x`) and is not currently reachable —
> reaching it needs a VPN, jump host, or firewall exception from the network
> admin. A VM on the laptop does **not** change this, because it shares the
> laptop's network. Migrating to the router later means swapping Paramiko for
> Netmiko (`device_type="mikrotik_routeros"`); the FastAPI layer is unchanged.

---

## Project structure

```
ssh-poc/
├── ssh_runner.py   # SSH logic: run_ssh_command (read) + run_sudo_command (write)
├── main.py         # FastAPI layer: /run (read) + /configure (write)
└── venv/           # Python virtual environment
```

---

## Part 1 — Python project setup (on the laptop / client)

```bash
mkdir ssh-poc && cd ssh-poc
python3 -m venv venv
source venv/bin/activate
pip install paramiko fastapi uvicorn
```

---

## Part 2 — Create the VM target with Multipass

```bash
# Install Multipass
sudo snap install multipass

# Launch an Ubuntu 24.04 VM named "target"
multipass launch --name target 24.04

# Find the VM's IP (look for the IPv4: line, e.g. 10.137.65.110)
multipass info target

# Open a shell inside the VM
multipass shell target
```

### Inside the VM — enable SSH and set up password login

```bash
# Ensure the SSH server is installed and running
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh

# Set a password for the ubuntu user (Multipass users have none by default)
sudo passwd ubuntu        # enter a password twice, e.g. poc12345

# Enable password authentication via a drop-in config
echo 'PasswordAuthentication yes' | sudo tee /etc/ssh/sshd_config.d/poc.conf
sudo systemctl restart ssh

# Verify the EFFECTIVE setting (this is the key check)
sudo sshd -T | grep passwordauthentication
```

### GOTCHA: password auth still shows "no"

Multipass cloud images ship a file that forces password auth off, which
overrides your drop-in. Find and fix it:

```bash
# Find which file disables it
sudo grep -ri passwordauthentication /etc/ssh/sshd_config /etc/ssh/sshd_config.d/

# The culprit is usually 60-cloudimg-settings.conf — flip it to yes
sudo sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' \
    /etc/ssh/sshd_config.d/60-cloudimg-settings.conf

sudo systemctl restart ssh

# Re-check — must now print: passwordauthentication yes
sudo sshd -T | grep passwordauthentication

# Leave the VM
exit
```

---

## Part 3 — Test SSH from the laptop to the VM

```bash
# Replace the IP with your VM's IP from `multipass info target`
ssh ubuntu@10.137.65.110
# Trust the host key (type: yes), then enter the password you set.
# If you land in the VM shell, it works. Then:
exit
```

---

## Part 4 — The code

### `ssh_runner.py`

```python
import paramiko


def run_ssh_command(host, username, password, command, port=22):
    """Read path: run a normal command and return its output."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # PoC only
    try:
        client.connect(host, port=port, username=username, password=password)
        stdin, stdout, stderr = client.exec_command(command)
        return {
            "stdout": stdout.read().decode(),
            "stderr": stderr.read().decode(),
            "exit_code": stdout.channel.recv_exit_status(),
        }
    finally:
        client.close()


def run_sudo_command(host, username, password, command, port=22):
    """Write path: run a command as root via sudo (-S reads pw from stdin)."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=username, password=password)
        stdin, stdout, stderr = client.exec_command(f"sudo -S -p '' {command}")
        stdin.write(password + "\n")
        stdin.flush()
        return {
            "stdout": stdout.read().decode(),
            "stderr": stderr.read().decode(),
            "exit_code": stdout.channel.recv_exit_status(),
        }
    finally:
        client.close()


if __name__ == "__main__":
    r = run_ssh_command("10.137.65.110", "ubuntu", "poc12345", "uname -a && uptime")
    print(r["stdout"])
```

### `main.py` (with API-key authentication)

Every request must send a secret in the `X-API-Key` header. The server reads the
expected key from the `API_KEY` environment variable and rejects anything that
doesn't match — before any SSH happens.

```python
import os
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from ssh_runner import run_ssh_command, run_sudo_command

app = FastAPI(title="SSH Automation PoC")

# Read the expected key from the environment (never hardcode it)
API_KEY = os.environ.get("API_KEY")


def verify_api_key(x_api_key: str = Header(None)):
    """Reject any request whose X-API-Key header doesn't match the server key."""
    if not API_KEY:
        # Fail closed: if the server has no key set, refuse everything.
        raise HTTPException(status_code=500, detail="API_KEY not configured on server")
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class CommandRequest(BaseModel):
    host: str
    username: str
    password: str
    command: str
    port: int = 22


@app.post("/run", dependencies=[Depends(verify_api_key)])          # read-only
def run(req: CommandRequest):
    try:
        return run_ssh_command(
            req.host, req.username, req.password, req.command, req.port
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/configure", dependencies=[Depends(verify_api_key)])    # write (sudo)
def configure(req: CommandRequest):
    try:
        return run_sudo_command(
            req.host, req.username, req.password, req.command, req.port
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## Part 5 — Run and test

```bash
# Activate the venv if not already
source venv/bin/activate

# Quick standalone test (no API)
python ssh_runner.py

# Set the API key the server will require (this terminal session)
export API_KEY="$(openssl rand -hex 32)"
echo "$API_KEY"          # note it down — needed in the X-API-Key header

# Start the API server
uvicorn main:app --reload
# Interactive docs: http://127.0.0.1:8000/docs
# In /docs, add the X-API-Key header (or click Authorize) with the key above.
```

> All requests must include `-H "X-API-Key: <your key>"`. A request without it
> (or with the wrong key) is rejected with HTTP 401 before any SSH runs.

### Test `/run` (read) — via curl

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"host":"10.137.65.110","username":"ubuntu","password":"12345","command":"uname -a && uptime"}'
```

### Test that auth works — omit the key, expect 401

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -d '{"host":"10.137.65.110","username":"ubuntu","password":"12345","command":"uptime"}'
# → {"detail":"Invalid or missing API key"}
```

### Test `/configure` (write) — change the login message

```bash
curl -X POST http://127.0.0.1:8000/configure \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"host":"10.137.65.110","username":"ubuntu","password":"12345","command":"bash -c \"echo '\''Changed via FastAPI'\'' > /etc/motd\""}'
```

### Verify the change landed

```bash
curl -X POST http://127.0.0.1:8000/run \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"host":"10.137.65.110","username":"ubuntu","password":"12345","command":"cat /etc/motd"}'
# stdout should be: Changed via FastAPI
```

---

## Useful Multipass commands

```bash
multipass list                              # list VMs and their IPs
multipass info target                       # details incl. current IP
multipass stop target                       # shut down (frees RAM/CPU)
multipass start target                      # boot back up (IP may change)
multipass delete target && multipass purge  # remove entirely
```

> The VM's IP can change after stop/start — re-check with `multipass info target`
> if SSH suddenly fails to connect.

---

## Part 6 — Automating it

There are two layers of automation. (A) is convenience; (B) is the actual job —
running defined commands/config against targets without hand-typing curl.

### A. One script to bring everything up

Create `start.sh` so you don't retype the startup each time:

```bash
#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

# Make sure the VM target is running
multipass start target 2>/dev/null || true

# Activate the venv and set the API key
source venv/bin/activate
export API_KEY="${API_KEY:-$(openssl rand -hex 32)}"
echo "API_KEY=$API_KEY"          # note this for your client calls

# Start the API (foreground; Ctrl+C to stop)
uvicorn main:app --host 127.0.0.1 --port 8000
```

```bash
chmod +x start.sh
./start.sh
```

### B. A client that runs a batch of commands against targets

This is the real automation: define your targets and the commands once, then run
them all in one go. Create `automate.py`:

```python
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
```

Install the client dependency and run it (server must be up, same `API_KEY`):

```bash
pip install requests
python automate.py
```

This loops over every target, runs the read checks, then applies the config
changes — the "change config multiple times a day" workflow, now one command.
To scale, move `TARGETS` into a separate `inventory.json`/`.yaml` and load it.

### C. Running it on a schedule (cron)

To run the automation automatically (e.g. a nightly config-sync), wrap it so the
`API_KEY` is available and add a cron entry:

```bash
# run-automation.sh
#!/usr/bin/env bash
cd ~/ssh-poc
source venv/bin/activate
export API_KEY="your-fixed-key-here"
python automate.py >> ~/ssh-poc/automation.log 2>&1
```

```bash
chmod +x run-automation.sh
crontab -e
# add this line to run every day at 02:00:
0 2 * * * /home/madiha/ssh-poc/run-automation.sh
```

> For scheduled runs you need a **fixed** `API_KEY` (not a random one each time),
> and the API server must be running as a background service. The clean way to
> keep the server always-on is a **systemd service** (see note below) rather than
> a terminal you have to leave open.

### Keeping the API server always running (systemd)

For anything beyond manual testing, run uvicorn as a systemd service so it starts
on boot and restarts on failure — instead of an open terminal. Create
`/etc/systemd/system/ssh-poc.service`:

```ini
[Unit]
Description=SSH Automation PoC API
After=network.target

[Service]
User=madiha
WorkingDirectory=/home/madiha/ssh-poc
Environment=API_KEY=your-fixed-key-here
ExecStart=/home/madiha/ssh-poc/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ssh-poc
sudo systemctl status ssh-poc      # confirm it's running
```

---

## Hardening TODO (before this is more than a PoC)

1. **[DONE] Authenticate the API.** Implemented via an `X-API-Key` header checked
   against the `API_KEY` env var (see `main.py` / Part 5). Next refinement:
   support multiple keys or per-key scopes if more than one caller needs access.
2. **Move credentials server-side.** Load target credentials from environment
   variables or a `.env` file (`python-dotenv`) instead of passing them in every
   request body.
3. **Restrict `/configure`.** Use an allowlist of permitted commands or templated
   operations rather than free-form command strings.
4. **Host key verification.** Replace `AutoAddPolicy` with a known_hosts check to
   prevent man-in-the-middle.
5. **Structured logging.** Log who ran what against which host — essential once it
   touches real infrastructure.
6. **Use HTTPS.** An API key sent over plain HTTP can be sniffed; put this behind
   TLS (a reverse proxy like Caddy/Nginx, or `uvicorn --ssl-*`) before it leaves
   localhost.

---

## Migrating to the real MikroTik (later)

Once the router is reachable (VPN / jump host / firewall exception):

```bash
pip install netmiko
```

Replace the Paramiko logic in `ssh_runner.py` with Netmiko:

```python
from netmiko import ConnectHandler

def push_config(host, username, password, config_commands):
    device = {
        "device_type": "mikrotik_routeros",
        "host": host, "username": username, "password": password,
    }
    conn = ConnectHandler(**device)
    output = conn.send_config_set(config_commands)  # the "change config" step
    conn.disconnect()
    return output
```

- `send_command()`  → read-only (show/print commands)
- `send_config_set([...])` → config changes
- RouterOS uses `/path command` syntax and **auto-saves** (no `write memory`).
- **Caution:** a wrong interface/firewall/routing line can lock you out of the
  device mid-change. Read first, change small, have a recovery path.

The FastAPI layer (`main.py`) does not change.
