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

_IS_WIN = sys.platform == "win32"
_SUPERVISOR_MODE = os.environ.get("SUPERVISOR_MODE", "").strip() == "1"

_NOOP_BROWSER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "noop.cmd" if _IS_WIN else "noop.sh",
)
_SUB_ENV = os.environ.copy()
_SUB_ENV["BROWSER"] = _NOOP_BROWSER

# ── Port base: fixed at 5000 (pure Demo version) ──
_BASE = 5000

_ALL_APPS = [
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
    {
        "id": "usg_virus_test",
        "name": "USG 测病毒",
        "cwd": os.path.join(BASE, "application", "usg_virus_test"),
        "cmd": [PYTHON, "app.py", str(_BASE + 5)],
        "port": _BASE + 5,
        "url": "/app/usg_virus_test/",
    },
    {
        "id": "fastip_report",
        "name": "FASTIP 测试报告",
        "cwd": os.path.join(BASE, "application", "fastip_report"),
        "cmd": [PYTHON, "app.py", str(_BASE + 6)],
        "port": _BASE + 6,
        "url": "/app/fastip_report/",
    },
]

# Demo version shows only all_in_one (配置生成).
# domain_capture (域名抓取) 依赖 playwright + 本地 Chromium，当前镜像未安装，
# 暂时隐藏；test_report 和 config_analyzer 也隐藏。
_HIDDEN_IDS = {"test_report", "config_analyzer", "domain_capture"}
APPS = [a for a in _ALL_APPS if a["id"] not in _HIDDEN_IDS]

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
    """Kill any process listening on the given port."""
    try:
        if _IS_WIN:
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
        else:
            # Linux: try fuser first, fallback to lsof + kill
            sp = subprocess
            r = sp.run(["fuser", "-k", f"{port}/tcp"],
                       capture_output=True, timeout=5)
            if r.returncode == 0:
                print(f"[portal] Killed stale process on port {port}")
            else:
                # fallback: lsof -ti :port | xargs kill -9
                lr = sp.run(["lsof", "-ti", f":{port}"],
                            capture_output=True, text=True, timeout=5)
                if lr.returncode == 0 and lr.stdout.strip():
                    for pid_str in lr.stdout.strip().split():
                        sp.run(["kill", "-9", pid_str],
                               capture_output=True, timeout=3)
                    print(f"[portal] Killed stale PIDs on port {port}")
    except Exception:
        pass


def _start_one(app: dict) -> None:
    """Start a single sub-app process."""
    if _SUPERVISOR_MODE:
        # supervisord manages sub-apps; portal only waits for port.
        if _wait_for_port(app["port"], timeout=15.0):
            print(f"[portal] {app['name']} ready at {app['url']}")
        else:
            print(f"[portal] WARNING: {app['name']} port {app['port']} not reachable after 15s")
        return

    _kill_port(app["port"])
    log_path = os.path.join(LOG_DIR, f"{app['id']}.log")
    try:
        log_fh = open(log_path, "a", encoding="utf-8")
        kwargs = {
            "cwd": app["cwd"],
            "stdout": log_fh,
            "stderr": log_fh,
            "env": _SUB_ENV,
            "stdin": subprocess.DEVNULL,
        }
        if _IS_WIN:
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(app["cmd"], **kwargs)
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
        if _SUPERVISOR_MODE:
            # supervisord manages lifecycle; portal only checks port.
            reachable = _port_open(app["port"])
            result.append({
                "id": app["id"],
                "name": app["name"],
                "url": app["url"],
                "port": app["port"],
                "alive": reachable,
                "reachable": reachable,
            })
        else:
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
