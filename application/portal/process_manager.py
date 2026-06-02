"""Sub-application process manager — spawn, health-check, restart, cleanup."""
import subprocess
import sys
import time
import socket
import atexit
import threading
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(os.path.dirname(_HERE))
PYTHON = sys.executable
LOG_DIR = os.path.join(_HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

_NOOP_BROWSER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "noop.cmd")
_SUB_ENV = os.environ.copy()
_SUB_ENV["BROWSER"] = _NOOP_BROWSER

# ── Runtime port switching: RELEASE_MODE=1 → 700x, otherwise → 500x ──
_RELEASE = os.environ.get("RELEASE_MODE", "").strip() == "1"
_BASE = 7000 if _RELEASE else 5000

APPS = [
    {
        "id": "all_in_one",
        "name": "配置生成",
        "cwd": os.path.join(BASE, "application", "all_in_one - cc", "web"),
        "cmd": [PYTHON, "app.py", str(_BASE + 3)],
        "port": _BASE + 3,
        "url": "/app/all_in_one/",
    },
    {
        "id": "test_report",
        "name": "测试报告",
        "cwd": os.path.join(BASE, "application", "自动做测试报告 - cc"),
        "cmd": [PYTHON, "app.py", str(_BASE + 2)],
        "port": _BASE + 2,
        "url": "/app/test_report/",
    },
    {
        "id": "domain_capture",
        "name": "域名抓取",
        "cwd": os.path.join(BASE, "application", "自动抓域名发2"),
        "cmd": [PYTHON, "app.py", str(_BASE + 1)],
        "port": _BASE + 1,
        "url": "/app/domain_capture/",
    },
    {
        "id": "config_analyzer",
        "name": "配置梳理",
        "cwd": os.path.join(BASE, "application", "自动梳理配置 - cc"),
        "cmd": [PYTHON, "app.py", str(_BASE + 4)],
        "port": _BASE + 4,
        "url": "/app/config_analyzer/",
    },
]

_processes = {}   # app_id -> subprocess.Popen
_running = True


def _port_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _wait_for_port(port: int, timeout: float = 30.0) -> bool:
    """Block until port is open or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


def _monitor_loop():
    """Background thread: restart any app whose process has died."""
    global _running
    while _running:
        for app in APPS:
            proc = _processes.get(app["id"])
            if proc is None:
                continue
            if proc.poll() is not None:
                print(f"[portal] {app['name']} (port {app['port']}) exited, restarting...")
                _start_one(app)
        time.sleep(3)


def _kill_port(port: int) -> None:
    """Kill any process listening on the given port (Windows only)."""
    if sys.platform != "win32":
        return
    try:
        import subprocess as sp
        result = sp.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = int(parts[-1])
                sp.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=5)
                print(f"[portal] Killed stale PID {pid} on port {port}")
    except Exception:
        pass


def _start_one(app: dict) -> None:
    """Start a single sub-app process."""
    _kill_port(app["port"])
    log_path = os.path.join(LOG_DIR, f"{app['id']}.log")
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
        proc = subprocess.Popen(
            app["cmd"],
            cwd=app["cwd"],
            stdout=log_fh,
            stderr=log_fh,
            env=_SUB_ENV,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _processes[app["id"]] = proc
        print(f"[portal] Starting {app['name']} (pid={proc.pid}, port={app['port']})...")
        if _wait_for_port(app["port"], timeout=15.0):
            print(f"[portal] {app['name']} ready at {app['url']}")
        else:
            print(f"[portal] WARNING: {app['name']} port {app['port']} not reachable after 15s")
    except Exception as e:
        print(f"[portal] ERROR starting {app['name']}: {e}")


def start_all() -> None:
    """Launch all sub-apps and begin monitoring."""
    print("[portal] Starting all sub-applications...")
    for app in APPS:
        _start_one(app)
    monitor = threading.Thread(target=_monitor_loop, daemon=True)
    monitor.start()


def shutdown_all() -> None:
    """Terminate all sub-app processes."""
    global _running
    _running = False
    for app_id, proc in _processes.items():
        if proc.poll() is None:
            print(f"[portal] Stopping {app_id} (pid={proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[portal] Force-killing {app_id}")
                proc.kill()
    print("[portal] All sub-apps stopped.")


def get_apps_status() -> list[dict]:
    """Return list of apps with their current status for the frontend."""
    result = []
    for app in APPS:
        proc = _processes.get(app["id"])
        alive = proc is not None and proc.poll() is None
        reachable = _port_open(app["port"]) if alive else False
        result.append({
            "id": app["id"],
            "name": app["name"],
            "url": app["url"],
            "port": app["port"],
            "alive": alive,
            "reachable": reachable,
        })
    return result


# Register cleanup on normal exit
atexit.register(shutdown_all)
