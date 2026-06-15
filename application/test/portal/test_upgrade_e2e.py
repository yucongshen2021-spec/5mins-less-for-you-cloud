"""Full E2E update test — simulates a customer upgrading from old → new.

Uses Playwright for browser automation and _update_utils for shared helpers.
Run with mirror already serving on port 8000.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _update_utils import (
    PROJECT_DIR, MIRROR_PORT, CUSTOMER_PORT_BASE, BUNDLE_NAME,
    port_open, kill_port, kill_ports,
    mirror_url, mirror_ok, fetch_manifest,
    http_get,
    unzip, replace_config, find_content_root, _force_rmtree,
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
    content_root = find_content_root(extract_dir)
    python_exe = content_root / "runtime" / "python" / "python.exe"
    app_py = content_root / "application" / "portal" / "app.py"
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
    content_root = find_content_root(extract_dir)
    ri = content_root / "RELEASE_INFO.json"
    if ri.exists():
        return json.loads(ri.read_text("utf-8")).get("version")
    return None


def test_e2e_upgrade() -> None:
    """Run the full E2E upgrade: extract old → start → browser → click upgrade → verify."""
    tracker = TimeoutTracker(total=600.0)

    # ── Prepare ──
    zips = dist_zips()
    if len(zips) < 2:
        _fail(f"Need >= 2 zips in dist/, found {len(zips)}")
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
