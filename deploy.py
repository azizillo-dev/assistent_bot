#!/usr/bin/env python3
"""Deploy taxibot to remote server via SSH"""
import os
import sys
import paramiko
from scp import SCPClient
import time

# Fix Windows encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# Server config
HOST = "45.148.29.33"
USER = "nabiyev"
PASS = "Senior0307"
REMOTE_DIR = "/home/nabiyev/taxibot"

# Local project dir
LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxibot")

# Files to upload
FILES_TO_UPLOAD = [
    "main.py",
    "config.py",
    "db.py",
    "handlers.py",
    "scheduler.py",
    "sender.py",
    "sessions_mgr.py",
    "requirements.txt",
    ".env",
]


def create_ssh_client():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=30)
    print("[+] Connected!")
    return ssh


def run_cmd(ssh, cmd, show_output=True):
    print(f"  > {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if show_output and out.strip():
        print(f"    {out.strip()}")
    if err.strip() and exit_code != 0:
        print(f"    WARN: {err.strip()}")
    return out, err, exit_code


def upload_files(ssh):
    print(f"\n[*] Uploading files to {REMOTE_DIR}...")
    
    with SCPClient(ssh.get_transport()) as scp:
        for f in FILES_TO_UPLOAD:
            local_path = os.path.join(LOCAL_DIR, f)
            if os.path.exists(local_path):
                remote_path = f"{REMOTE_DIR}/{f}"
                print(f"  [+] {f}")
                scp.put(local_path, remote_path)
            else:
                print(f"  [-] {f} not found locally, skipping")
    
    # Upload data and sessions dirs if they have content
    for dirname in ["data", "sessions"]:
        local_subdir = os.path.join(LOCAL_DIR, dirname)
        if os.path.isdir(local_subdir) and os.listdir(local_subdir):
            print(f"  [+] {dirname}/")
            with SCPClient(ssh.get_transport()) as scp:
                for item in os.listdir(local_subdir):
                    item_path = os.path.join(local_subdir, item)
                    if os.path.isfile(item_path):
                        scp.put(item_path, f"{REMOTE_DIR}/{dirname}/{item}")
                        print(f"    [+] {dirname}/{item}")

    print("[+] All files uploaded!")


def setup_server(ssh):
    print("\n[*] Setting up server...")
    
    # Create directories
    run_cmd(ssh, f"mkdir -p {REMOTE_DIR}/data {REMOTE_DIR}/sessions")
    
    # Check Python version
    out, _, _ = run_cmd(ssh, "python3 --version")
    
    # Create virtual environment if not exists
    run_cmd(ssh, f"cd {REMOTE_DIR} && python3 -m venv venv 2>/dev/null || true")
    
    # Install requirements
    print("\n[*] Installing dependencies...")
    run_cmd(ssh, f"cd {REMOTE_DIR} && source venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt")
    
    print("[+] Server setup complete!")


def deploy_bot(ssh):
    print("\n[*] Deploying bot...")
    
    # Kill existing screen session if any
    run_cmd(ssh, "screen -S taxibot -X quit 2>/dev/null || true")
    time.sleep(1)
    
    # Start new screen session with the bot
    start_cmd = (
        f"screen -dmS taxibot bash -c '"
        f"cd {REMOTE_DIR} && "
        f"source venv/bin/activate && "
        f"python3 main.py"
        f"'"
    )
    run_cmd(ssh, start_cmd)
    time.sleep(3)
    
    # Check if screen is running
    out, _, _ = run_cmd(ssh, "screen -ls | grep taxibot || echo 'NO_SCREEN'")
    
    if "taxibot" in out and "NO_SCREEN" not in out:
        print("[+] Bot is running in screen session 'taxibot'!")
        print(f"\n[i] Useful commands:")
        print(f"    ssh {USER}@{HOST}")
        print(f"    screen -r taxibot     # Attach to bot screen")
        print(f"    Ctrl+A then D         # Detach from screen")
    else:
        print("[-] Screen session not found. Checking for errors...")
        run_cmd(ssh, f"cd {REMOTE_DIR} && source venv/bin/activate && timeout 5 python3 main.py 2>&1 || true")


def main():
    ssh = None
    try:
        ssh = create_ssh_client()
        
        # 1. Create remote dirs
        run_cmd(ssh, f"mkdir -p {REMOTE_DIR}/data {REMOTE_DIR}/sessions")
        
        # 2. Upload files
        upload_files(ssh)
        
        # 3. Setup environment
        setup_server(ssh)
        
        # 4. Deploy
        deploy_bot(ssh)
        
        print("\n[+] Deployment complete!")
        
    except Exception as e:
        print(f"\n[-] Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if ssh:
            ssh.close()
            print("[*] SSH connection closed")


if __name__ == "__main__":
    main()
