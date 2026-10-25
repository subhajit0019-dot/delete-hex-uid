import os
import sys
import threading
import subprocess

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def run_bot():
    print("[+] Launching Discord Bot...")
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "bot.py")], cwd=BASE_DIR)

def run_dashboard():
    print("[+] Launching Delete Hex Web Dashboard on http://localhost:5000 ...")
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "dashboard.py")], cwd=BASE_DIR)

if __name__ == "__main__":
    print("=" * 60)
    print("   Delete Hex - BOT & WEB DASHBOARD LAUNCHER")
    print("=" * 60)

    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_dash = threading.Thread(target=run_dashboard, daemon=True)

    t_bot.start()
    t_dash.start()

    try:
        t_bot.join()
        t_dash.join()
    except KeyboardInterrupt:
        print("\n[*] Shutting down services.")
