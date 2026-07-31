#!/usr/bin/env python3
"""Kill all Norms-AI server processes and restart.

Usage:
  python restart.py            # default port 8080
  python restart.py 9000       # custom port
  python restart.py 8080 --all # kill ALL python processes
"""
import subprocess, sys, os, time, socket

NORMS_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else "8080"
KILL_ALL = "--all" in sys.argv

CHECK_PORTS = [8080, 8081, 9000, 9001]


def run(cmd_list, timeout=10):
    try:
        return subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def find_pids_on_ports():
    pids = set()
    result = run(["netstat", "-ano"])
    if not result:
        return pids
    for line in result.stdout.splitlines():
        for port in CHECK_PORTS:
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                if pid.isdigit():
                    pids.add(pid)
    return pids


def kill_pids(pids):
    for pid in pids:
        print(f"  Killing PID {pid}")
        run(["taskkill", "/f", "/pid", pid])


def kill_by_name(name):
    run(["taskkill", "/f", "/im", name])


def wait_port_free(port, timeout=10):
    for _ in range(timeout * 2):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        try:
            sock.connect(("127.0.0.1", int(port)))
            sock.close()
            time.sleep(0.5)
        except (ConnectionRefusedError, OSError):
            return True
    return False


def start_server():
    os.chdir(NORMS_DIR)
    subprocess.run([sys.executable, "start.py", "--no-open", "--port", PORT])


def main():
    print()
    print("  ============================================")
    print(f"   Norms-AI Restart  |  Port: {PORT}")
    print("  ============================================")
    print()

    print("  [1/3] Killing running processes...")

    pids = find_pids_on_ports()
    if pids:
        kill_pids(pids)

    kill_by_name("pythonw.exe")

    if KILL_ALL:
        print("  Killing all python.exe processes...")
        kill_by_name("python.exe")
        time.sleep(1)

    print()
    print("  [2/3] Waiting for ports to release...")
    if not wait_port_free(PORT):
        print(f"  WARNING: Port {PORT} may still be in use")

    time.sleep(1)

    print()
    print("  [3/3] Starting server...")
    print("  ============================================")
    print()

    start_server()

    print()
    input("  Server stopped. Press Enter to restart, or Ctrl+C to quit.")
    print()
    os.execl(sys.executable, sys.executable, __file__, *sys.argv[1:])


if __name__ == "__main__":
    main()
