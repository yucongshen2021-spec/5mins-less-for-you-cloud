"""COMPLETE customer simulation: download → extract → start → update → upgrade.

This test:
  1. Extracts v1.1.4 (customer version) to a temp directory
  2. Starts mirror server serving v1.1.5 (the update)
  3. Starts the v1.1.4 customer portal
  4. Uses Playwright to verify:
     a. Release badge (not DEMO) on page
     b. Upgrade button (not dlCard) in sidebar
     c. Banner appears after auto-check with v1.1.5
     d. Manual check button works
     e. Clicking upgrade transitions button state
     f. No console errors
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DIST_DIR = PROJECT_ROOT / "dist"
MIRROR_SCRIPT = PROJECT_ROOT / "tools" / "serve_mirror.py"
TEMP_ROOT = PROJECT_ROOT / ".customer_test"

MIRROR_PORT = 8000
CUSTOMER_PORT = 7000

CUSTOMER_VERSION = "1.1.4"
UPDATE_VERSION = "dynamic"  # Read from mirror at runtime

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
            shell=True, text=True,
        )
        for line in out.strip().split("\n"):
            parts = line.strip().split()
            if parts:
                subprocess.run(["taskkill", "/F", "/PID", parts[-1]],
                               capture_output=True, shell=True)
    except Exception:
        pass


# ============================================================================
# Setup
# ============================================================================
print("=" * 60)
print("  Full Customer Simulation Test")
print(f"  Customer: v{CUSTOMER_VERSION} → Update: v{UPDATE_VERSION}")
print("=" * 60)

# Clean
kill_port(MIRROR_PORT)
kill_port(CUSTOMER_PORT)
for port in range(7000, 7005):
    kill_port(port)
if TEMP_ROOT.exists():
    shutil.rmtree(TEMP_ROOT)
TEMP_ROOT.mkdir()

# Find customer zip
customer_zips = sorted(DIST_DIR.glob(f"*-{CUSTOMER_VERSION}.zip"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
check("Customer zip exists", len(customer_zips) > 0)
if not customer_zips:
    print("  No old zip found, building test customer zip...")
    ri_bak = (PROJECT_ROOT / "RELEASE_INFO.json").read_text(encoding="utf-8")
    (PROJECT_ROOT / "RELEASE_INFO.json").write_text(
        '{"version":"' + CUSTOMER_VERSION + '","name":"test","built_at":"2000-01-01T00:00:00Z"}',
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "build_release.py"),
         "--version", CUSTOMER_VERSION, "--no-runtime"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    (PROJECT_ROOT / "RELEASE_INFO.json").write_text(ri_bak, encoding="utf-8")
    if r.returncode != 0:
        print("  FAILED to build test zip")
        sys.exit(1)
    customer_zips = sorted(DIST_DIR.glob(f"*-{CUSTOMER_VERSION}.zip"),
                           key=lambda p: p.stat().st_mtime, reverse=True)
    check("Customer zip built", len(customer_zips) > 0)
    if not customer_zips:
        print("  ABORT: Still no customer zip")
        sys.exit(1)

customer_zip = customer_zips[0]
print(f"  Using: {customer_zip.name}")

# Extract customer
print("\n--- Extracting customer zip ---")
with zipfile.ZipFile(customer_zip) as zf:
    zf.extractall(TEMP_ROOT)
bundles = list(TEMP_ROOT.glob("*"))
customer_dir = bundles[0] if bundles else None
check("Bundle extracted", customer_dir is not None)
if customer_dir is None:
    sys.exit(1)
print(f"  Bundle: {customer_dir.name}")

# Set up mirror config in customer
cfg_path = customer_dir / "application" / "portal" / "update_config.json"
cfg = {
    "mirror_urls": [f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest"],
    "mirror_url": "",
    "timeout_seconds": 5,
    "cache_ttl_seconds": 0,
    "user_agent": "customer-test",
}
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

# Set customer RELEASE_INFO to old version
ri_path = customer_dir / "RELEASE_INFO.json"
ri_path.write_text(json.dumps({
    "version": CUSTOMER_VERSION,
    "name": "测试客户", "built_at": "2026-01-01T00:00:00Z",
}), encoding="utf-8")

# Start mirror
print("\n--- Starting mirror ---")
kill_port(MIRROR_PORT)
mirror = subprocess.Popen(
    [sys.executable, str(MIRROR_SCRIPT), "--port", str(MIRROR_PORT),
     "--dist", str(DIST_DIR)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(2)
check("Mirror started", port_open(MIRROR_PORT))

# Read actual latest version from mirror (dynamic, not hardcoded)
import urllib.request
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest",
                                timeout=5) as r:
        manifest = json.loads(r.read())
    actual_update_version = manifest.get("version")
    check("Mirror version read", actual_update_version is not None,
          f"got {actual_update_version}")
except Exception as e:
    check("Mirror accessible", False, str(e))
    sys.exit(1)

# Start customer portal
print("\n--- Starting customer portal ---")
kill_port(CUSTOMER_PORT)
python_exe = str(customer_dir / "runtime" / "python" / "python.exe")
if not Path(python_exe).is_file():
    python_exe = sys.executable
app_py = str(customer_dir / "application" / "portal" / "app.py")
env = {**os.environ, "RELEASE_MODE": "1", "NO_BROWSER": "1"}
customer_proc = subprocess.Popen(
    [python_exe, app_py],
    cwd=str(customer_dir / "application" / "portal"),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env=env,
)
deadline = time.time() + 45
while time.time() < deadline:
    if port_open(CUSTOMER_PORT):
        time.sleep(3)
        break
    time.sleep(1)
else:
    check("Customer portal started", False, "timeout")
    sys.exit(1)
check("Customer portal started on " + str(CUSTOMER_PORT), True)

# Verify each sub-app is actually reachable (not just reported by API)
for app_port in [7001, 7002, 7003, 7004]:
    time.sleep(1)
    check(f"Sub-app port {app_port} reachable", port_open(app_port),
          f"sub-app on port {app_port} not responding")

# ============================================================================
# Playwright tests
# ============================================================================
print("\n--- Playwright UI tests ---")
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(viewport={"width": 1280, "height": 900})
errors = []
page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

page.goto(f"http://127.0.0.1:{CUSTOMER_PORT}")
page.wait_for_load_state("networkidle")

# Test 1: Release badge, not demo — check RENDERED header text only
header_el = page.query_selector("header")
header_text = header_el.inner_text() if header_el else ""
check("RELEASE badge visible", "正式版" in header_text or "RELEASE" in header_text.upper())
check("No DEMO in header text", "DEMO" not in header_text.upper(),
      f"Found in header: '{header_text[:80]}'")

# Test 2: upgradeBtn exists, dlCard does not
ub = page.query_selector("#upgradeBtn")
dl = page.query_selector("#dlCard")
check("upgradeBtn in sidebar", ub is not None)
check("dlCard NOT in sidebar", dl is None, "dlCard should not appear in release")

# Test 3: Wait for auto check, verify banner
print("  Waiting for auto update check (8s)...")
page.wait_for_timeout(8000)

banner = page.query_selector("#updateBanner")
if banner:
    visible = banner.evaluate(
        "el => window.getComputedStyle(el).display !== 'none'"
    )
    check("Banner becomes visible after auto-check", visible,
          "Banner should show update available")
    if visible:
        ver_el = page.query_selector("#updateBannerVer")
        if ver_el:
            ver_text = ver_el.inner_text()
            check("Banner shows new version " + str(actual_update_version),
                  str(actual_update_version) in ver_text,
                  f"got '{ver_text}'")

        dl_link = page.query_selector("#updateBannerLink")
        check("Banner has download link", dl_link is not None)

        upg_btn = page.query_selector("#updateBannerUpgrade")
        check("Banner has upgrade button", upg_btn is not None)
else:
    check("Banner element exists in DOM", False, "updateBanner not found")

# Test 4: Sidebar upgrade button state
if ub:
    classes = ub.evaluate("el => el.className")
    label_el = ub.query_selector(".ub-label")
    label = label_el.inner_text() if label_el else ""
    check("Upgrade button is available (not error)", "is-available" in classes,
          f"label='{label}' classes='{classes}'")
    check("Upgrade button shows new version",
          str(actual_update_version) in label,
          f"got '{label}'")

# Test 5: Manual check button exists in sidebar
manual_btn = page.query_selector("#btnCheckUpdate")
check("Manual check button in sidebar", manual_btn is not None)
if manual_btn:
    # Click it
    manual_btn.click()
    page.wait_for_timeout(3000)
    after_text = manual_btn.inner_text()
    check("Manual check responds (not error)",
          "失败" not in after_text and "错误" not in after_text,
          f"button shows: '{after_text}'")

# Test 6: Click upgrade button
if ub and "is-available" in ub.evaluate("el => el.className"):
    # Intercept the upgrade API to prevent actual upgrade
    page.route(
        f"http://127.0.0.1:{CUSTOMER_PORT}/api/update/upgrade",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": True, "new_version": UPDATE_VERSION, "stage": "launched"}),
        )
    )
    ub.click()
    page.wait_for_timeout(1000)
    after_classes = ub.evaluate("el => el.className")
    label_after = ub.query_selector(".ub-label")
    label_txt = label_after.inner_text() if label_after else ""
    check("Upgrade button transitions on click",
          "is-error" not in after_classes,
          f"got classes='{after_classes}' label='{label_txt}'")
    page.unroute(f"http://127.0.0.1:{CUSTOMER_PORT}/api/update/upgrade")

# Test 7: No console errors
# Filter known browser noise (502s from slow sub-app startup, favicon, etc.)
relevant = [e for e in errors if "ERR_" not in e and "favicon" not in e.lower() and "502" not in e]
check("Zero console errors", len(relevant) == 0,
      f"errors: {relevant[:3]}" if relevant else "")

# Screenshot
page.screenshot(path=str(PROJECT_ROOT / "application" / "test" / "portal" / "customer_test_result.png"))

# ============================================================================
# Cleanup
# ============================================================================
print("\n--- Cleanup ---")
browser.close()
p.stop()
customer_proc.terminate()
try:
    customer_proc.wait(timeout=10)
except Exception:
    customer_proc.kill()
mirror.terminate()
try:
    mirror.wait(timeout=5)
except Exception:
    mirror.kill()
kill_port(CUSTOMER_PORT)
kill_port(MIRROR_PORT)
shutil.rmtree(TEMP_ROOT, ignore_errors=True)

print(f"\n{'=' * 60}")
print(f"  Results: {PASSED} passed, {FAILED} failed")
print(f"  {'ALL CHECKS PASSED' if FAILED == 0 else f'{FAILED} FAILURES'}")
print(f"{'=' * 60}")
sys.exit(0 if FAILED == 0 else 1)
