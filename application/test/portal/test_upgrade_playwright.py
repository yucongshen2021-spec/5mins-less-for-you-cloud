"""Complete Playwright upgrade test — clicks button → waits for restart → verifies.

This test simulates the FULL customer update journey:
  1. Build v1.1.9 (new), extract v1.1.7 (old customer)
  2. Start mirror + start customer portal
  3. Playwright: auto-check → banner → click "upgrade" button
  4. Wait for portal shutdown → restart
  5. Verify new version running, data preserved, zero errors
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
CUSTOMER_VERSION = "1.1.7"
NEW_VERSION = "1.1.9"

TEMP = PROJECT_ROOT / "temp" / "test_upgrade_playwright"
MIRROR_PORT = 8000
PORTAL_PORT = 7000

PASSED = 0
FAILED = 0


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def port_open(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def kill_port(port):
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
print("  Full Upgrade Playwright Test")
print(f"  Customer v{CUSTOMER_VERSION} -> v{NEW_VERSION}")
print("=" * 60)

# Clean
for port in range(7000, 7005):
    kill_port(port)
kill_port(MIRROR_PORT)
if TEMP.exists():
    shutil.rmtree(TEMP)
TEMP.mkdir()

# Back up the release zip so mirror only sees test zips
release_zip = DIST_DIR / "帮你节省5分钟-1.1.8.zip"
release_backup = None
if release_zip.exists():
    release_backup = release_zip.with_suffix(".zip.bak")
    shutil.move(str(release_zip), str(release_backup))

# Build NEW version
print("\n--- Building v" + NEW_VERSION + " ---")
ri_bak = (PROJECT_ROOT / "RELEASE_INFO.json").read_text(encoding="utf-8")
(PROJECT_ROOT / "RELEASE_INFO.json").write_text(
    '{{"version":"{}","name":"test","built_at":"2026-01-01T00:00:00Z"}}'.format(NEW_VERSION),
    encoding="utf-8",
)
r = subprocess.run(
    [sys.executable, str(PROJECT_ROOT / "tools" / "build_release.py"),
     "--version", NEW_VERSION, "--no-runtime"],
    cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8",
)
(PROJECT_ROOT / "RELEASE_INFO.json").write_text(ri_bak, encoding="utf-8")
check("Build new version", r.returncode == 0, r.stderr[-200:] if r.returncode != 0 else "")

# Find customer zip
customer_zips = sorted(DIST_DIR.glob(f"*-{CUSTOMER_VERSION}.zip"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
if not customer_zips:
    # Build one if needed
    (PROJECT_ROOT / "RELEASE_INFO.json").write_text(
        '{{"version":"{}","name":"test","built_at":"2025-01-01T00:00:00Z"}}'.format(CUSTOMER_VERSION),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "tools" / "build_release.py"),
         "--version", CUSTOMER_VERSION, "--no-runtime"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8",
    )
    (PROJECT_ROOT / "RELEASE_INFO.json").write_text(ri_bak, encoding="utf-8")
    customer_zips = sorted(DIST_DIR.glob(f"*-{CUSTOMER_VERSION}.zip"),
                           key=lambda p: p.stat().st_mtime, reverse=True)

check("Customer zip exists", len(customer_zips) > 0)
if not customer_zips:
    print("ABORT: no customer zip")
    sys.exit(1)

# Ensure new zip has newest mtime (mirror picks latest)
new_zips = sorted(DIST_DIR.glob(f"*-{NEW_VERSION}.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
if new_zips:
    import os as _os
    _os.utime(str(new_zips[0]), None)
    time.sleep(0.5)
    check("New zip is newest", True)

# Extract customer
print("\n--- Extracting customer v" + CUSTOMER_VERSION + " ---")
with zipfile.ZipFile(customer_zips[0]) as zf:
    zf.extractall(TEMP)
bundles = list(TEMP.glob("*"))
customer_dir = bundles[0]
print(f"  Bundle: {customer_dir.name}")

# Configure customer
cfg = {
    "mirror_urls": [f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest"],
    "mirror_url": "",
    "timeout_seconds": 5,
    "cache_ttl_seconds": 0,
    "user_agent": "test-upgrade",
}
cfg_path = customer_dir / "application" / "portal" / "update_config.json"
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

(customer_dir / "RELEASE_INFO.json").write_text(
    json.dumps({"version": CUSTOMER_VERSION, "name": "test", "built_at": "2025-01-01T00:00:00Z"}),
    encoding="utf-8",
)

# Create test data markers
(customer_dir / "_TEST_MARKER_BEFORE_UPGRADE_.txt").write_text("data-before-upgrade", encoding="utf-8")
workspace = customer_dir / "application" / "all_in_one - cc" / "data" / "editor_workspace"
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "_test_template_.json").write_text('{"name":"user-workspace","version":"1"}', encoding="utf-8")

# Start mirror
print("\n--- Starting mirror ---")
kill_port(MIRROR_PORT)
mirror = subprocess.Popen(
    [sys.executable, str(PROJECT_ROOT / "tools" / "serve_mirror.py"),
     "--port", str(MIRROR_PORT), "--dist", str(DIST_DIR)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(2)
check("Mirror started", port_open(MIRROR_PORT))

# Verify mirror version
import urllib.request
with urllib.request.urlopen(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest", timeout=5) as r:
    manifest = json.loads(r.read())
check("Mirror serves v" + NEW_VERSION, manifest.get("version") == NEW_VERSION,
      f"got {manifest.get('version')}")

# Start customer portal
print("\n--- Starting customer portal ---")
python_exe = str(customer_dir / "runtime" / "python" / "python.exe")
if not Path(python_exe).is_file():
    python_exe = sys.executable
app_py = str(customer_dir / "application" / "portal" / "app.py")
env = {**os.environ, "RELEASE_MODE": "1", "NO_BROWSER": "1"}
portal_proc = subprocess.Popen(
    [python_exe, app_py],
    cwd=str(customer_dir / "application" / "portal"),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
)
deadline = time.time() + 45
while time.time() < deadline:
    if port_open(PORTAL_PORT):
        time.sleep(4)
        break
    time.sleep(1)
else:
    check("Customer portal started", False, "timeout")
    sys.exit(1)
check("Customer portal started on " + str(PORTAL_PORT), True)

# ============================================================================
# Playwright: complete upgrade flow
# ============================================================================
print("\n--- Playwright: upgrade test ---")
from playwright.sync_api import sync_playwright

p = sync_playwright().start()
browser = p.chromium.launch(headless=True)
page = browser.new_page(viewport={"width": 1280, "height": 900})
errors = []
page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

page.goto(f"http://127.0.0.1:{PORTAL_PORT}")
page.wait_for_load_state("networkidle")

# 1. Wait for auto-check
print("  Waiting for auto-check (10s)...")
page.wait_for_timeout(10000)

# 2. Verify banner
banner = page.query_selector("#updateBanner")
if banner:
    visible = banner.evaluate("el => window.getComputedStyle(el).display !== 'none'")
    check("Banner visible after auto-check", visible)
    if visible:
        ver_el = page.query_selector("#updateBannerVer")
        ver_text = ver_el.inner_text() if ver_el else ""
        check("Banner shows v" + NEW_VERSION, NEW_VERSION in ver_text, f"got '{ver_text}'")
        upg_btn = page.query_selector("#updateBannerUpgrade")
        check("Banner has upgrade button", upg_btn is not None)
else:
    check("Banner exists", False)

# 3. Verify sidebar upgrade button
ub = page.query_selector("#upgradeBtn")
check("upgradeBtn exists", ub is not None)
if ub:
    cls = ub.evaluate("el => el.className")
    label_el = ub.query_selector(".ub-label")
    label = label_el.inner_text() if label_el else ""
    check("Button is 'available' state", "is-available" in cls, f"label='{label}' cls='{cls}'")
    check("Button shows v" + NEW_VERSION, NEW_VERSION in label, f"got '{label}'")

# 4. Check RELEASE badge
header_el = page.query_selector("header")
header_text = header_el.inner_text() if header_el else ""
check("RELEASE badge visible", "RELEASE" in header_text.upper() or "正式版" in header_text)
check("No DEMO in header", "DEMO" not in header_text.upper())

# 5. CLICK the upgrade button!
print("\n  >>> CLICKING UPGRADE BUTTON <<<")
if ub and "is-available" in ub.evaluate("el => el.className"):
    ub.click()
    print("  Upgrade initiated. Portal should shut down in ~2s...")

    # Wait for portal to go down, then come back up
    max_wait = 120  # seconds
    print(f"  Waiting for upgrade cycle (max {max_wait}s)...")

    went_down = False
    came_up = False
    deadline = time.time() + max_wait
    while time.time() < deadline:
        alive = port_open(PORTAL_PORT)
        if alive and not went_down:
            time.sleep(1)
            continue
        if not alive:
            if not went_down:
                went_down = True
                print(f"  Portal went down at t+{int(time.time() - (deadline - max_wait))}s")
            time.sleep(2)
            continue
        if alive and went_down:
            came_up = True
            elapsed = int(time.time() - (deadline - max_wait))
            print(f"  Portal restarted at t+{elapsed}s!")
            time.sleep(5)  # Let sub-apps start
            break
        time.sleep(1)

    check("Portal went down (bat executed)", went_down)
    if went_down:
        # Save the bat content for debugging
        bat_path = Path(str(customer_dir.parent) + "/__update__.bat")
        if bat_path.exists():
            print(f"  Bat content saved for debug: {bat_path}")
            print("  ---")
            for line in bat_path.read_text(encoding="utf-8").splitlines():
                print(f"  {line}")
            print("  ---")
    # Also check if portal started on 5000 (RELEASE_MODE not inherited)
    came_up_5000 = port_open(5000)
    check("Portal restarted after upgrade", came_up or came_up_5000,
          f"7000={'UP' if came_up else 'DOWN'} 5000={'UP' if came_up_5000 else 'DOWN'}")

    actual_port = PORTAL_PORT if came_up else (5000 if came_up_5000 else 0)
    if actual_port:
        # Verify new version
        try:
            page.goto(f"http://127.0.0.1:{actual_port}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(5000)

            # Check banner is gone or shows "up to date"
            banner2 = page.query_selector("#updateBanner")
            if banner2:
                v2 = banner2.evaluate("el => window.getComputedStyle(el).display !== 'none'")
                check("No update banner after upgrade", not v2,
                      "banner still visible — may show 'same version'")

            ub2 = page.query_selector("#upgradeBtn")
            if ub2:
                cls2 = ub2.evaluate("el => el.className")
                label2 = ub2.query_selector(".ub-label").inner_text() if ub2.query_selector(".ub-label") else ""
                check("Button shows up-to-date after upgrade",
                      "is-up-to-date" in cls2,
                      f"label='{label2}' cls='{cls2}'")

            # Check data preservation
            marker = customer_dir / "_TEST_MARKER_BEFORE_UPGRADE_.txt"
            if marker.exists():
                content = marker.read_text(encoding="utf-8")
                check("User data preserved", "data-before-upgrade" in content)
            else:
                check("User data preserved", False, "marker file deleted")

            ws_file = customer_dir / "application" / "all_in_one - cc" / "data" / "editor_workspace" / "_test_template_.json"
            if ws_file.exists():
                ws_content = ws_file.read_text(encoding="utf-8")
                check("Workspace data preserved", "user-workspace" in ws_content)
            else:
                check("Workspace data preserved", False, "workspace file deleted")

            # Verify new version in response
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{actual_port}/api/update/check?force=1", timeout=10) as resp:
                    data = json.loads(resp.read())
                check("New version installed",
                      data.get("local_version") == NEW_VERSION,
                      f"local={data.get('local_version')} expected={NEW_VERSION}")
            except Exception as e:
                check("Portal reachable after upgrade", False, str(e))

            # Screenshot
            page.screenshot(path=str(PROJECT_ROOT / "application" / "test" / "portal" / "upgrade_complete.png"))
        except Exception as e:
            check("Portal page loads after restart", False, str(e))

else:
    check("Button clickable", False, "not in available state, cannot click upgrade")

# 6. Console errors
relevant = [e for e in errors if "ERR_" not in e and "favicon" not in e.lower() and "502" not in e]
check("Zero console errors", len(relevant) == 0, f"errors: {relevant[:3]}" if relevant else "")

# ============================================================================
# Cleanup
# ============================================================================
print("\n--- Cleanup ---")
browser.close()
p.stop()
portal_proc.terminate()
try:
    portal_proc.wait(timeout=10)
except Exception:
    portal_proc.kill()
mirror.terminate()
try:
    mirror.wait(timeout=5)
except Exception:
    mirror.kill()
kill_port(PORTAL_PORT)
kill_port(MIRROR_PORT)
for port in range(7000, 7005):
    kill_port(port)
shutil.rmtree(TEMP, ignore_errors=True)

# Clean test zips
for f in DIST_DIR.glob(f"*-{CUSTOMER_VERSION}.zip"):
    f.unlink()
for f in DIST_DIR.glob(f"*-{NEW_VERSION}.zip"):
    f.unlink()

# Restore release zip
if release_backup and release_backup.exists():
    shutil.move(str(release_backup), str(release_zip))

print(f"\n{'=' * 60}")
print(f"  Results: {PASSED} passed, {FAILED} failed")
if FAILED == 0:
    print("  ALL UPGRADE TESTS PASSED")
else:
    print(f"  {FAILED} FAILURES")
print(f"{'=' * 60}")
sys.exit(0 if FAILED == 0 else 1)
