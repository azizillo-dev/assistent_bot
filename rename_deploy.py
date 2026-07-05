#!/usr/bin/env python3
"""Rename taxibot -> taxibot_brat on server and update .env"""
import os
import sys
import paramiko
from scp import SCPClient
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

HOST = "45.148.29.33"
USER = "nabiyev"
PASS = "Senior0307"
OLD_DIR = "/home/nabiyev/taxibot"
NEW_DIR = "/home/nabiyev/taxibot_brat"
OLD_SCREEN = "taxibot"
NEW_SCREEN = "taxibot_brat"

LOCAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "taxibot")


def run_cmd(ssh, cmd):
    print(f"  > {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    exit_code = stdout.channel.recv_exit_status()
    if out.strip():
        print(f"    {out.strip()}")
    if err.strip() and exit_code != 0:
        print(f"    WARN: {err.strip()}")
    return out, err, exit_code


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=30)
    print("[+] Connected!")

    try:
        # 1. Kill old screen session
        print("\n[*] Stopping old screen session...")
        run_cmd(ssh, f"screen -S {OLD_SCREEN} -X quit 2>/dev/null || true")
        time.sleep(2)

        # 2. Rename directory
        print(f"\n[*] Renaming {OLD_DIR} -> {NEW_DIR}...")
        run_cmd(ssh, f"mv {OLD_DIR} {NEW_DIR}")
        
        # Verify rename
        out, _, _ = run_cmd(ssh, f"ls -la {NEW_DIR}/main.py")
        if "main.py" not in out:
            print("[-] ERROR: Rename failed!")
            return

        # 3. Upload updated .env with new ALLOWED_USERS
        print("\n[*] Uploading updated .env...")
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(os.path.join(LOCAL_DIR, ".env"), f"{NEW_DIR}/.env")
        print("[+] .env updated!")

        # Verify .env content
        run_cmd(ssh, f"cat {NEW_DIR}/.env")

        # 4. Start new screen session with new name
        print(f"\n[*] Starting bot in screen '{NEW_SCREEN}'...")
        start_cmd = (
            f"screen -dmS {NEW_SCREEN} bash -c '"
            f"cd {NEW_DIR} && "
            f"source venv/bin/activate && "
            f"python3 main.py"
            f"'"
        )
        run_cmd(ssh, start_cmd)
        time.sleep(3)

        # 5. Verify
        out, _, _ = run_cmd(ssh, f"screen -ls | grep {NEW_SCREEN} || echo 'NO_SCREEN'")
        if NEW_SCREEN in out and "NO_SCREEN" not in out:
            print(f"\n[+] Bot is running in screen '{NEW_SCREEN}'!")
        else:
            print("[-] Screen not found, checking errors...")
            run_cmd(ssh, f"cd {NEW_DIR} && source venv/bin/activate && timeout 5 python3 main.py 2>&1 || true")

        # 6. Show all screen sessions
        print("\n[*] All screen sessions:")
        run_cmd(ssh, "screen -ls")

        print("\n[+] Done! Summary:")
        print(f"    Directory: {NEW_DIR}")
        print(f"    Screen:    {NEW_SCREEN}")
        print(f"    ALLOWED_USERS: 7238759485, 1634302416")

    except Exception as e:
        print(f"[-] Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        ssh.close()
        print("[*] SSH closed")


if __name__ == "__main__":
    main()
