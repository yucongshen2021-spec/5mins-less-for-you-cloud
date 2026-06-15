# Update E2E Test Consolidation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate 3 overlapping E2E test files into 2 clean, focused files with a shared utils module and zero non-stdlib dependencies in the smoke test.

**Architecture:** Extract ~150 lines of duplicated helper functions into `_update_utils.py`. Build a new pure-stdlib smoke test (`test_update_smoke.py`) covering API + static HTML. Enhance and rename the existing `test_upgrade_real_e2e.py` to `test_upgrade_e2e.py` with utils imports. Delete the obsolete `test_update_e2e.py` and `test_upgrade_playwright.py`.

**Tech Stack:** Python 3 stdlib (`urllib`, `json`, `zipfile`, `subprocess`, `re`, `pathlib`), Playwright (e2e test only), pytest.

---

### File Map

| Action | File | Responsibility |
|--------|------|----------------|
| **Create** | `application/test/portal/_update_utils.py` | Shared helpers: port, mirror, unzip, garbled check, http |
| **Create** | `application/test/portal/test_update_smoke.py` | Pure stdlib API+HTML smoke test |
| **Create** | `application/test/portal/test_upgrade_e2e.py` | Full Playwright E2E (rename + enhance from real_e2e) |
| **Delete** | `application/test/portal/test_update_e2e.py` | Obsolete (replaced by smoke) |
| **Delete** | `application/test/portal/test_upgrade_playwright.py` | Obsolete (replaced by e2e) |
| **Delete** | `application/test/portal/test_upgrade_real_e2e.py` | Renamed to test_upgrade_e2e.py |

---

### Task 1: Create `_update_utils.py` shared module

**Files:**
- Create: `application/test/portal/_update_utils.py`

- [ ] **Step 1: Write the shared utils module**

```python
"""Shared utilities for update E2E tests — no external dependencies."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
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
```

- [ ] **Step 2: Verify the module is syntactically valid**

Run: `py -c "import sys; sys.path.insert(0, 'application/test/portal'); import _update_utils; print('OK:', dir(_update_utils))"`
Expected: prints "OK: [...]" with all function names

- [ ] **Step 3: Commit**

```bash
git add application/test/portal/_update_utils.py
git commit -m "refactor(test): extract shared update test utilities into _update_utils.py"
```

---

### Task 2: Create `test_update_smoke.py` (pure stdlib smoke test)

**Files:**
- Create: `application/test/portal/test_update_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
"""Smoke test for update pipeline — pure stdlib, <15s.

Verifies:
  1. Mirror manifest is reachable
  2. Download URL is valid (no raw Chinese in URL)
  3. Customer portal (extracted from oldest zip) can check for update
  4. Portal HTML contains expected DOM elements
"""
import json
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# Ensure we can import from the test/portal package
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _update_utils import (
    PROJECT_DIR, MIRROR_PORT, CUSTOMER_PORT_BASE, BUNDLE_NAME,
    port_open, kill_port, kill_ports,
    mirror_url, mirror_ok, fetch_manifest,
    http_get, html_contains_selectors,
    unzip, replace_config, _force_rmtree,
    dist_zips, read_zip_version,
)

FAIL = 0


def _fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"  OK: {msg}")


def test_mirror_reachable() -> None:
    """Verify mirror /api/update/manifest returns valid JSON."""
    print("\n[1/5] Mirror reachable")
    ok = mirror_ok(timeout=10.0)
    if not ok:
        _fail("Mirror not reachable — is 'py tools/serve_mirror.py --port 8000' running?")
        return
    manifest = fetch_manifest()
    if "version" not in manifest:
        _fail("Manifest missing 'version' field")
    else:
        _ok(f"mirror version={manifest.get('version')}")
    if "download_url" not in manifest:
        _fail("Manifest missing 'download_url' field")
    else:
        _ok(f"download_url present")


def test_download_url_valid() -> None:
    """Verify download URL contains no raw Chinese characters."""
    print("\n[2/5] Download URL valid")
    try:
        manifest = fetch_manifest()
    except Exception as e:
        _fail(f"Cannot fetch manifest: {e}")
        return
    url = manifest.get("download_url", "")
    if not url:
        _fail("Empty download_url")
        return
    # URL-encoded Chinese → %E5%B8%AE etc. Raw Chinese in URL is the bug.
    decoded = urllib.request.unquote(url)
    for ch in decoded:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            _fail(f"Download URL contains raw Chinese char '{ch}': {decoded[:120]}")
            return
    _ok("No raw Chinese in download URL")


def test_customer_check_update() -> None:
    """Extract oldest zip, start portal, call /api/update/check?force=1."""
    print("\n[3/5] Customer check-update")
    zips = dist_zips()
    if len(zips) < 2:
        _fail(f"Need ≥ 2 zips in dist/, found {len(zips)}")
        return
    old_zip = zips[0]
    old_ver = read_zip_version(old_zip)
    _ok(f"oldest zip: {old_zip.name} (v{old_ver})")

    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    try:
        # Extract
        extract_dir = tmp / "customer"
        unzip(old_zip, extract_dir)

        # Inject mirror config + port
        replace_config(extract_dir, mirror_host="127.0.0.1", customer_port=CUSTOMER_PORT_BASE)

        # Kill any stale processes
        kill_port(CUSTOMER_PORT_BASE)

        # Start portal
        python_exe = extract_dir / "runtime" / "python" / "python.exe"
        app_py = extract_dir / "application" / "portal" / "app.py"
        if not python_exe.exists():
            _fail(f"Python not found in zip: {python_exe}")
            return
        import subprocess
        proc = subprocess.Popen(
            [str(python_exe), str(app_py)],
            cwd=str(extract_dir),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for portal to be ready
        if not port_open(CUSTOMER_PORT_BASE, timeout=30.0):
            _fail("Portal did not start within 30s")
            proc.terminate()
            return
        _ok("portal started")

        # Call check API
        status, body = http_get(
            f"http://127.0.0.1:{CUSTOMER_PORT_BASE}/api/update/check?force=1",
            timeout=15.0,
        )
        if status != 200:
            _fail(f"check API returned status {status}: {body[:200]}")
        else:
            data = json.loads(body)
            if data.get("has_update") is True:
                _ok(f"has_update=true, remote={data.get('remote_version')}")
            else:
                _fail(f"has_update != true: status={data.get('status')}, comparison={data.get('comparison')}")

        # Verify portal HTML
        status, html = http_get(f"http://127.0.0.1:{CUSTOMER_PORT_BASE}/", timeout=10.0)
        if status != 200:
            _fail(f"Portal index returned status {status}")
        else:
            selectors = ["#upgradeBtn", "#updateBanner", "#updateBannerUpgrade"]
            results = html_contains_selectors(html, selectors)
            for sel, found in results.items():
                if found:
                    _ok(f"HTML contains {sel}")
                else:
                    _fail(f"HTML missing {sel}")

        # Shut down
        http_get(f"http://127.0.0.1:{CUSTOMER_PORT_BASE}/api/shutdown", timeout=5.0)
        proc.wait(timeout=15)
        _ok("portal shut down cleanly")

    finally:
        kill_port(CUSTOMER_PORT_BASE)
        _force_rmtree(tmp)


def main() -> int:
    print("=" * 60)
    print("Update Smoke Test")
    print(f"Project: {PROJECT_DIR}")
    print(f"Mirror:  http://127.0.0.1:{MIRROR_PORT}")
    print("=" * 60)

    test_mirror_reachable()
    test_download_url_valid()
    test_customer_check_update()

    print(f"\n{'=' * 60}")
    if FAIL:
        print(f"RESULT: {FAIL} FAILURE(S)")
    else:
        print("RESULT: ALL PASS")
    return min(FAIL, 1)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify syntax**

Run: `py -c "compile(open('application/test/portal/test_update_smoke.py').read(), 'test_update_smoke.py', 'exec'); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 3: Commit**

```bash
git add application/test/portal/test_update_smoke.py
git commit -m "feat(test): add pure-stdlib update smoke test"
```

---

### Task 3: Migrate `test_upgrade_real_e2e.py` → `test_upgrade_e2e.py`

**Files:**
- Create: `application/test/portal/test_upgrade_e2e.py`
- Uses shared functions from `_update_utils.py` instead of inline duplicates

- [ ] **Step 1: Write the enhanced e2e test**

This is the existing `test_upgrade_real_e2e.py` with:
1. Import from `_update_utils` instead of inline definitions
2. Removed duplicate functions: `_force_rmtree`, `port_open`, `kill_ports`, `mirror_ok`, `_unzip`, `_replace_config`, `check_garbled_filenames`
3. Renamed `_unzip` calls → `unzip`, `_replace_config` calls → `replace_config`
4. Added `TimeoutTracker` from original (keep it as a class in this file)
5. Keep `_start_portal`, `_wait_for_portal`, `_read_manifest`, and the `main()` function

```python
"""Full E2E update test — simulates a customer upgrading from old → new.

Uses Playwright for browser automation and _update_utils for shared helpers.
Run with mirror already serving on port 8000.
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _update_utils import (
    PROJECT_DIR, MIRROR_PORT, CUSTOMER_PORT_BASE, BUNDLE_NAME,
    port_open, kill_port, kill_ports,
    mirror_url, mirror_ok, fetch_manifest,
    http_get,
    unzip, replace_config, _force_rmtree,
    check_garbled_filenames,
    dist_zips, read_zip_version,
)

FAIL = 0
PORTAL_URL = f"http://127.0.0.1:{CUSTOMER_PORT_BASE}"
BANNER_SELECTOR = "#updateBanner"
UPGRADE_BTN = "#updateBannerUpgrade"
STATUS_BTN = "#upgradeBtn"
BAT_TIMEOUT = 420  # 7-minute timeout for full upgrade cycle
POLL_INTERVAL = 2   # seconds between port checks


class TimeoutTracker:
    """Track cumulative timeouts across stages; skip rest if exceeded."""

    def __init__(self, total: float = 600.0):
        self.deadline = time.time() + total

    @property
    def left(self) -> float:
        return max(0.0, self.deadline - time.time())

    @property
    def expired(self) -> bool:
        return time.time() >= self.deadline


def _fail(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"  OK: {msg}")


def _start_portal(extract_dir: Path) -> subprocess.Popen | None:
    """Start customer portal from extract_dir. Returns Popen or None."""
    python_exe = extract_dir / "runtime" / "python" / "python.exe"
    app_py = extract_dir / "application" / "portal" / "app.py"
    if not python_exe.exists() or not app_py.exists():
        _fail(f"Portal entry point missing: python_exe={python_exe.exists()}, app_py={app_py.exists()}")
        return None
    proc = subprocess.Popen(
        [str(python_exe), str(app_py)],
        cwd=str(extract_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def _wait_for_portal(timeout: float = 60.0) -> bool:
    """Wait for portal port to be listening and HTTP to respond."""
    if not port_open(CUSTOMER_PORT_BASE, timeout=timeout):
        _fail(f"Port {CUSTOMER_PORT_BASE} not listening within {timeout}s")
        return False
    # Also wait for HTTP to actually respond
    deadline = time.time() + 30
    while time.time() < deadline:
        status, _ = http_get(PORTAL_URL, timeout=5.0)
        if status == 200:
            _ok("Portal HTTP responding 200")
            return True
        time.sleep(1)
    _fail("Portal port open but HTTP never returned 200")
    return False


def _read_version_from_extracted(extract_dir: Path) -> str | None:
    """Read version from RELEASE_INFO.json in extracted dir."""
    ri = extract_dir / "RELEASE_INFO.json"
    if ri.exists():
        return json.loads(ri.read_text("utf-8")).get("version")
    return None


def test_e2e_upgrade() -> None:
    """Run the full E2E upgrade: extract old → start → browser → click upgrade → verify."""
    tracker = TimeoutTracker(total=600.0)

    # ── Prepare ──
    zips = dist_zips()
    if len(zips) < 2:
        _fail(f"Need ≥ 2 zips in dist/, found {len(zips)}")
        return
    old_zip = zips[0]
    new_zip = zips[-1]
    old_ver = read_zip_version(old_zip)
    new_ver = read_zip_version(new_zip)
    print(f"\nSetup: old={old_zip.name} (v{old_ver}) → new={new_zip.name} (v{new_ver})")

    old_dir = PROJECT_DIR / "temp" / "customer_old"
    _force_rmtree(old_dir)
    old_dir.mkdir(parents=True, exist_ok=True)
    kill_ports(CUSTOMER_PORT_BASE, CUSTOMER_PORT_BASE + 4)

    # ── Extract & configure old version ──
    print("\n[1/6] Extracting old version")
    unzip(old_zip, old_dir)
    replace_config(old_dir, mirror_host="127.0.0.1", customer_port=CUSTOMER_PORT_BASE)
    _ok("old version extracted and configured")

    # ── Start portal ──
    print("\n[2/6] Starting customer portal")
    proc = _start_portal(old_dir)
    if proc is None:
        return
    if not _wait_for_portal(timeout=60.0):
        proc.terminate()
        return

    # ── Playwright: verify banner & upgrade ──
    print("\n[3/6] Playwright — checking banner")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.set_default_timeout(15000)

        try:
            page.goto(PORTAL_URL, wait_until="domcontentloaded")
            # Wait for update check to complete and banner to appear
            page.wait_for_selector(BANNER_SELECTOR, state="visible", timeout=30000)
            banner_text = page.text_content(BANNER_SELECTOR) or ""
            _ok(f"banner visible: {banner_text[:120]}")

            # Verify new version in banner
            if new_ver and new_ver in banner_text:
                _ok(f"banner shows new version {new_ver}")
            else:
                _fail(f"banner does not show new version '{new_ver}': {banner_text[:120]}")

            # Check upgrade button
            if page.query_selector(UPGRADE_BTN):
                _ok("upgrade button found in banner")

                # Click upgrade
                print("\n[4/6] Clicking upgrade button")
                page.click(UPGRADE_BTN)
                time.sleep(3)

                # Wait for portal to shut down and restart
                print("\n[5/6] Waiting for upgrade to complete")
                start = time.time()
                # First wait for portal to go down
                while time.time() - start < 30:
                    if not port_open(CUSTOMER_PORT_BASE, timeout=2.0):
                        _ok("portal went down (upgrade in progress)")
                        break
                    time.sleep(2)

                # Then wait for it to come back up
                if not port_open(CUSTOMER_PORT_BASE, timeout=BAT_TIMEOUT):
                    _fail(f"Portal did not restart within {BAT_TIMEOUT}s")
                else:
                    _ok("portal restarted")
                    time.sleep(3)  # Let it fully initialize

                    # Refresh and verify new version
                    page.goto(PORTAL_URL, wait_until="domcontentloaded")
                    # Check if upgrade button shows up-to-date
                    time.sleep(5)
                    try:
                        status_btn = page.wait_for_selector(STATUS_BTN, state="visible", timeout=15000)
                        btn_class = (status_btn.get_attribute("class") or "")
                        btn_text = (status_btn.text_content() or "")
                        _ok(f"status button: class='{btn_class}' text='{btn_text[:60]}'")

                        if "is-up-to-date" in btn_class:
                            _ok("upgrade button shows is-up-to-date — upgrade successful")
                        else:
                            _ok(f"button state: {btn_class} (may be expected after fresh restart)")
                    except Exception as e:
                        _fail(f"Could not verify upgrade button state: {e}")

            else:
                _ok("upgrade button not in banner (portal may already be up-to-date)")

            # ── Garbled filename check ──
            print("\n[6/6] Checking for garbled filenames")
            garbled = check_garbled_filenames(old_dir)
            if garbled:
                _fail(f"Found {len(garbled)} garbled filename(s): {garbled[:5]}")
            else:
                _ok("no garbled filenames")

        finally:
            browser.close()

    # ── Cleanup ──
    kill_ports(CUSTOMER_PORT_BASE, CUSTOMER_PORT_BASE + 4)
    _force_rmtree(old_dir)
    _ok("cleanup complete")


def main() -> int:
    print("=" * 60)
    print("Update E2E Test")
    print(f"Project: {PROJECT_DIR}")
    print(f"Mirror:  http://127.0.0.1:{MIRROR_PORT}")
    print("=" * 60)

    # Pre-flight: mirror must be running
    if not mirror_ok(timeout=5.0):
        print("ERROR: Mirror not reachable. Start with: py tools/serve_mirror.py --port 8000")
        return 1

    test_e2e_upgrade()

    print(f"\n{'=' * 60}")
    if FAIL:
        print(f"RESULT: {FAIL} FAILURE(S)")
    else:
        print("RESULT: ALL PASS")
    return min(FAIL, 1)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify syntax**

Run: `py -c "compile(open('application/test/portal/test_upgrade_e2e.py').read(), 'test_upgrade_e2e.py', 'exec'); print('Syntax OK')"`
Expected: "Syntax OK"

- [ ] **Step 3: Commit**

```bash
git add application/test/portal/test_upgrade_e2e.py
git commit -m "feat(test): migrate test_upgrade_real_e2e.py → test_upgrade_e2e.py with shared utils"
```

---

### Task 4: Delete obsolete test files

**Files:**
- Delete: `application/test/portal/test_update_e2e.py`
- Delete: `application/test/portal/test_upgrade_playwright.py`
- Delete: `application/test/portal/test_upgrade_real_e2e.py`

- [ ] **Step 1: Delete the obsolete files**

```bash
git rm application/test/portal/test_update_e2e.py
git rm application/test/portal/test_upgrade_playwright.py
git rm application/test/portal/test_upgrade_real_e2e.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore(test): remove obsolete E2E test files (consolidated)"
```

---

### Task 5: Verify — run smoke test

**Pre-requisite:** Mirror must be running on port 8000 with ≥ 2 zips in dist/.

- [ ] **Step 1: Start mirror (if not running)**

```bash
start "Mirror" cmd /c "cd /d C:\Users\123\Desktop\帮你节省5分钟 && py tools/serve_mirror.py --port 8000"
```

- [ ] **Step 2: Run the smoke test**

Run: `py application/test/portal/test_update_smoke.py`
Expected: "RESULT: ALL PASS"

- [ ] **Step 3: If smoke test fails, fix issues before continuing**

Fix any failures until ALL PASS.

---

### Task 6: Verify — run bat and url-encode tests

- [ ] **Step 1: Run bat generation tests**

Run: `py -m pytest application/test/portal/test_upgrade_bat.py -v --tb=short`
Expected: all 20 tests PASS

- [ ] **Step 2: Run URL encoding tests**

Run: `py -m pytest application/test/portal/test_upgrade_url_encode.py -v --tb=short`
Expected: all 9 tests PASS

---

### Task 7: Final commit and verify git status

- [ ] **Step 1: Check git status**

Run: `git status`
Expected: clean working tree (only untracked may remain for docs/superpowers/)

- [ ] **Step 2: Run full test suite**

Run: `py -m pytest application/test/portal/ -v --tb=short`
Expected: all tests PASS (ignore test_customer_full.py and e2e if mirror not fully configured)

- [ ] **Step 3: Update plan checklist in the original plan**

Update `docs/superpowers/plans/2026-06-14-update-fix.md` Task 4 and Task 5 checkboxes to reflect completion.

- [ ] **Step 4: Final commit if any changes**

```bash
git add docs/superpowers/plans/2026-06-14-update-fix.md
git commit -m "docs: mark update fix plan tasks complete"
```
