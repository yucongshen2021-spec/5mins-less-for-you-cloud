"""Shared utilities for update E2E tests — no external dependencies."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[3]
MIRROR_PORT = 8000
CUSTOMER_PORT_BASE = 7000
BUNDLE_NAME = "帮你节省5分钟"


# ── port helpers ──────────────────────────────────────────────

def port_open(port: int, timeout: float = 30.0) -> bool:
    """Poll until port is LISTENING or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True,
        )
        if f":{port}" in r.stdout and "LISTENING" in r.stdout:
            return True
        time.sleep(1)
    return False


def kill_port(port: int) -> None:
    """Kill any process holding *port*."""
    subprocess.run(
        f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{port}\') do taskkill /F /PID %a >nul 2>&1',
        shell=True, capture_output=True,
    )


def kill_ports(start_port: int, end_port: int) -> None:
    """Kill processes on all ports in [start_port, end_port]."""
    for p in range(start_port, end_port + 1):
        kill_port(p)


# ── mirror helpers ────────────────────────────────────────────

def mirror_url(path: str = "/api/update/manifest") -> str:
    return f"http://127.0.0.1:{MIRROR_PORT}{path}"


def mirror_ok(timeout: float = 5.0) -> bool:
    """Check if mirror is reachable."""
    try:
        req = urllib.request.Request(mirror_url(), method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return "version" in data
    except Exception:
        return False


def fetch_manifest() -> dict:
    """Fetch mirror manifest, return parsed JSON dict."""
    req = urllib.request.Request(mirror_url(), method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── http helpers (pure stdlib) ─────────────────────────────────

def http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    """Return (status_code, body_text)."""
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def http_post(url: str, body: dict, timeout: float = 10.0) -> tuple[int, str]:
    """Return (status_code, body_text)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


# ── HTML verification ─────────────────────────────────────────

def html_contains_selectors(html: str, selectors: list[str]) -> dict[str, bool]:
    """Check whether each CSS id/class selector exists in HTML.

    Returns dict mapping selector → found (bool).
    Only checks id (#xxx) and class (.yyy) selectors.
    """
    result = {}
    for sel in selectors:
        if sel.startswith("#"):
            # id selector — look for id="xxx" or id='xxx'
            name = sel[1:]
            found = bool(re.search(rf'id=["\']{re.escape(name)}["\']', html))
        elif sel.startswith("."):
            # class selector — look for class="...xxx..." or class='...xxx...'
            name = sel[1:]
            found = bool(re.search(rf'class=["\'][^"\']*\b{re.escape(name)}\b[^"\']*["\']', html))
        else:
            found = sel in html
        result[sel] = found
    return result


# ── zip / unzip helpers ───────────────────────────────────────

def _force_rmtree(path: Path) -> None:
    """Robust rmtree — handles Windows permission/locked files."""
    if not path.exists():
        return

    def _on_error(func, p, exc_info):
        try:
            os.chmod(p, 0o777)
            func(p)
        except Exception:
            pass

    for _ in range(3):
        try:
            shutil.rmtree(path, onerror=_on_error)
            return
        except Exception:
            time.sleep(1)
    # Last resort
    try:
        subprocess.run(["cmd", "/c", "rmdir", "/s", "/q", str(path)],
                       capture_output=True, timeout=30)
    except Exception:
        pass


def unzip(zip_path: Path, dest_dir: Path) -> None:
    """Extract zip to dest_dir. Dest_dir is cleared first."""
    _force_rmtree(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Try Python zipfile first
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest_dir)
        return
    except Exception:
        pass

    # Fallback: PowerShell Expand-Archive
    subprocess.run([
        "powershell", "-Command",
        f"Expand-Archive -Path '{zip_path}' -DestinationPath '{dest_dir}' -Force"
    ], capture_output=True, timeout=120)


def replace_config(extract_dir: Path, mirror_host: str = "127.0.0.1",
                   customer_port: int = CUSTOMER_PORT_BASE) -> None:
    """Inject mirror URL and port into an extracted release."""
    config_path = extract_dir / "application" / "portal" / "update_config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text("utf-8"))
        cfg["mirror_urls"] = [f"http://{mirror_host}:{MIRROR_PORT}/api/update/manifest"]
        config_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")

    # Replace port 5000 → customer_port in app.py
    app_py = extract_dir / "application" / "portal" / "app.py"
    if app_py.exists():
        text = app_py.read_text("utf-8")
        text = re.sub(r"\b5000\b", str(customer_port), text)
        app_py.write_text(text, "utf-8")


# ── garbled filename check ────────────────────────────────────

def check_garbled_filenames(start_dir: Path) -> list[str]:
    """Walk dir, return list of filenames containing garbled-encoding patterns."""
    garbled = []
    patterns = [
        re.compile(r"[\x80-\xff]{3,}"),   # 3+ high bytes in a row (GBK mojibake)
        re.compile(r"\?{2,}[^\s]"),        # ?? prefix (GBK → ASCII fallback)
        re.compile(r"[ÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖ×ØÙÚÛÜÝÞß]{2,}"),  # Western mojibake of CJK
    ]
    for root, dirs, files in os.walk(str(start_dir)):
        for fname in files:
            for pat in patterns:
                if pat.search(fname):
                    garbled.append(os.path.join(root, fname))
                    break
    return garbled


# ── dist helpers ──────────────────────────────────────────────

def dist_zips() -> list[Path]:
    """Return sorted list of release zips in dist/ by mtime (oldest first)."""
    dist = PROJECT_DIR / "dist"
    if not dist.is_dir():
        return []
    zips = sorted(
        dist.glob(f"{BUNDLE_NAME}-*.zip"),
        key=lambda p: p.stat().st_mtime,
    )
    return zips


def read_zip_version(zip_path: Path) -> str | None:
    """Read version from RELEASE_INFO.json inside a zip."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open("RELEASE_INFO.json") as f:
                info = json.loads(f.read().decode("utf-8"))
                return info.get("version")
    except Exception:
        return None
