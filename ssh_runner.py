import paramiko

def run_ssh_command(host, username, password, command, port=22):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=port, username=username, password=password)
        # -S tells sudo to read the password from stdin
        stdin, stdout, stderr = client.exec_command(f"sudo -S {command}")
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
    r = run_sudo_command(
        "127.0.0.1", "madiha", "91375",
        "bash -c \"echo 'Managed by automation PoC' > /etc/motd\""
    )
    print("exit:", r["exit_code"])
    print("out:", r["stdout"])
    print("err:", r["stderr"])