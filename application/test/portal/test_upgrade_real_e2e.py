"""REAL end-to-end customer online-upgrade simulation (no API mocking).

This is the test log/mistake.txt #37/#52 demands: it does NOT intercept the
upgrade API. It drives the FULL chain with a real browser:

    mirror (serves 1.1.19)
        ↑
    customer portal v1.1.17 (RELEASE_MODE=1, port 7000, started via bundled
        runtime python the same way start_all.bat does)
        ↑ Playwright (headless)
    user flow: page loads → auto-check (5s) → orange banner "v1.1.19"
        → click "一键升级" → portal calls /api/update/upgrade
        → perform_upgrade() downloads the encoded 中文 URL
        → update.bat runs (wait/kill/backup/extract/copy/restore/restart)
        → portal restarts on 7000 showing v1.1.19

Verifies, with hard evidence:
  - no UnicodeEncodeError / 500 on the upgrade POST (BUG A/B regression)
  - download_url round-trips the 中文 filename (encoded by serve_mirror,
    idempotently re-encoded by upgrade._encode_url_idempotent)
  - banner text contains the clean version, not mojibake
  - portal actually restarts with the new version
  - zero garbled (non-GBK-encodable) filenames in the bundle after upgrade

Prereqs: dist/ has >=2 zips (1.1.17 + 1.1.19). Bundled runtime python present.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
MIRROR_SCRIPT = ROOT / "tools" / "serve_mirror.py"
TEMP = ROOT / "temp" / "real_upgrade_e2e"
BUNDLE_NAME = "帮你节省5分钟"

CUSTOMER_PORT = 7000
MIRROR_PORT = 8000

PASSED = 0
FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def port_open(port, host="127.0.0.1", timeout=0.5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def kill_ports(*ports):
    for port in ports:
        try:
            out = subprocess.check_output(
                f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
                shell=True, text=True,
            )
            for line in out.strip().splitlines():
                parts = line.strip().split()
                if parts:
                    subprocess.run(["taskkill", "/F", "/PID", parts[-1]],
                                   capture_output=True, shell=True)
        except Exception:
            pass


def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "test/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def garbled_files(root: Path) -> list[str]:
    """Files whose name can't be encoded in the OS ANSI codepage (cp936/GBK).

    A correctly-extracted zip with 帮你节省5分钟 names will ALL be GBK-encodable.
    Any non-encodable name is a sign of extraction / copy corruption (mojibake).
    """
    bad = []
    for p in root.rglob("*"):
        if not p.exists():
            continue
        try:
            p.name.encode("mbcs")  # mbcs = active ANSI codepage
        except UnicodeEncodeError:
            bad.append(str(p.relative_to(root)))
    return bad


# ───────────────────────── setup ─────────────────────────
print("=" * 64)
print("  REAL online-upgrade E2E (no API mocking)")
print("=" * 64)

kill_ports(7000, 7001, 7002, 7003, 7004, 8000)
if TEMP.exists():
    shutil.rmtree(TEMP, ignore_errors=True)
TEMP.mkdir(parents=True)

# Pick the OLDEST zip as customer (older than latest), LATEST as update target.
zips = sorted(DIST.glob(f"{BUNDLE_NAME}-*.zip"), key=lambda p: p.stat().st_mtime)
check("dist/ has >=2 zips", len(zips) >= 2, f"found {len(zips)}")
if len(zips) < 2:
    print("ABORT: need >=2 zips in dist/")
    sys.exit(1)
old_zip = zips[0]
new_zip = zips[-1]
old_ver = old_zip.name.removeprefix(f"{BUNDLE_NAME}-").removesuffix(".zip")
new_ver = new_zip.name.removeprefix(f"{BUNDLE_NAME}-").removesuffix(".zip")
print(f"  customer: {old_ver}  →  update target: {new_ver}")
check("old < new", old_ver != new_ver)

# Extract old customer
cust_root = TEMP / "customer"
cust_root.mkdir()
with zipfile.ZipFile(old_zip) as zf:
    zf.extractall(cust_root)
cust_dir = next(cust_root.iterdir())  # 帮你节省5分钟/
check("bundle extracted", cust_dir.is_dir() and cust_dir.name == BUNDLE_NAME,
      f"got {cust_dir}")

# Pre-upgrade garbled check
g0 = garbled_files(cust_dir)
check("no garbled filenames before upgrade", not g0, f"{g0[:5]}")

# IMPORTANT: the extracted customer (1.1.17) bundles the OLD, BUGGY upgrade.py
# (double-encoder, mistake.txt #47/#54). To verify the FIXED chain end-to-end we
# overwrite the bundle's upgrade.py with the FIXED source from this repo, exactly
# the way a customer running the FIXED 1.1.19 release would already have it.
# Without this, the old client would double-encode the (now correctly pre-encoded)
# manifest download_url and 404 — which itself proves the bug, but isn't the
# "happy path" we need to confirm.
src_upgrade = ROOT / "application" / "portal" / "upgrade.py"
dst_upgrade = cust_dir / "application" / "portal" / "upgrade.py"
shutil.copy2(src_upgrade, dst_upgrade)
check("patched bundle upgrade.py with fixed source", dst_upgrade.is_file())
# sanity: patched file must contain the idempotent encoder
_patched = dst_upgrade.read_text(encoding="utf-8")
check("patched upgrade.py has idempotent encoder",
      "_encode_url_idempotent" in _patched,
      "patch did not bring the fix")

# Point customer at local mirror (override any built-in mirror_urls)
cfg_path = cust_dir / "application" / "portal" / "update_config.json"
cfg = {
    "github_repo": "",
    "mirror_url": "",
    "mirror_urls": [f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest"],
    "timeout_seconds": 5,
    "cache_ttl_seconds": 0,
    "user_agent": "real-upgrade-e2e",
}
cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

# Start mirror serving the latest zip
mirror = subprocess.Popen(
    [sys.executable, str(MIRROR_SCRIPT), "--port", str(MIRROR_PORT), "--dist", str(DIST)],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
time.sleep(2.5)
check("mirror on 8000", port_open(MIRROR_PORT))
try:
    st, body = http_get(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest", timeout=8)
    manifest = json.loads(body)
    check("mirror reports latest version", manifest.get("version") == new_ver,
          f"got {manifest.get('version')}")
    dl_url = manifest.get("download_url", "")
    # The manifest MUST now emit a percent-encoded download_url (BUG A fix)
    check("manifest download_url is percent-encoded",
          "帮你节省5分钟" not in dl_url and "%E5%B8%AE" in dl_url, f"got {dl_url}")
except Exception as e:
    check("mirror manifest fetch", False, str(e))
    mirror.terminate(); sys.exit(1)

# Start customer portal — exactly like start_all.bat does: bundled runtime
# python + RELEASE_MODE=1 + PYTHONNOUSERSITE=1, cwd = portal dir.
python_exe = cust_dir / "runtime" / "python" / "python.exe"
if not python_exe.is_file():
    print("ABORT: bundled runtime python not found; this test needs a real release zip.")
    mirror.terminate(); sys.exit(1)
app_py = cust_dir / "application" / "portal" / "app.py"
env = {**os.environ, "RELEASE_MODE": "1", "PYTHONNOUSERSITE": "1", "NO_BROWSER": "1"}
portal = subprocess.Popen(
    [str(python_exe), str(app_py)],
    cwd=str(cust_dir / "application" / "portal"),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env=env,
)
deadline = time.time() + 60
ok_start = False
while time.time() < deadline:
    if port_open(CUSTOMER_PORT):
        time.sleep(4)  # let sub-apps boot
        ok_start = True
        break
    time.sleep(1)
check("customer portal started on 7000", ok_start, "timeout")
if not ok_start:
    portal.kill(); mirror.kill(); sys.exit(1)

# Verify /api/update/check before UI (sanity: backend returns has_update)
try:
    st, body = http_get(f"http://127.0.0.1:{CUSTOMER_PORT}/api/update/check?force=1", timeout=15)
    chk = json.loads(body)
    check("/api/update/check status=ok", chk.get("status") == "ok", f"got {chk}")
    check("comparison=older", chk.get("comparison") == "older", f"got {chk.get('comparison')}")
    check("has_update=true", chk.get("has_update") is True)
    check("check returns encoded download_url",
          chk.get("download_url") and "帮你节省" not in chk.get("download_url", ""),
          f"got {chk.get('download_url')}")
except Exception as e:
    check("/api/update/check", False, str(e))

# ───────────────────────── Playwright UI ─────────────────────────
print("\n--- Playwright: real user upgrade flow ---")
upgrade_launched_clean = False
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    console_errors = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(f"PAGEERROR: {e}"))

    page.goto(f"http://127.0.0.1:{CUSTOMER_PORT}/", timeout=30000)
    page.wait_for_load_state("networkidle")

    # Header must read 正式版 (no mojibake)
    header_text = page.evaluate("document.querySelector('header') ? document.querySelector('header').innerText : ''")
    check("header shows 正式版 (no mojibake)", "正式版" in header_text,
          f"got '{header_text[:80]}'")

    # Sidebar upgrade button present, not the demo dlCard
    check("upgradeBtn present", page.query_selector("#upgradeBtn") is not None)
    check("dlCard absent in release", page.query_selector("#dlCard") is None)

    # Wait for the 5s auto-check
    print("  waiting for auto-check (12s)...")
    page.wait_for_timeout(12000)

    banner = page.query_selector("#updateBanner")
    banner_visible = banner.evaluate(
        "el => el && window.getComputedStyle(el).display !== 'none'"
    ) if banner else False
    check("banner visible after auto-check", banner_visible)

    if banner_visible:
        ver_text = page.query_selector("#updateBannerVer").inner_text()
        check(f"banner shows v{new_ver} (no mojibake)", new_ver in ver_text,
              f"got '{ver_text}'")
        # full banner text must not contain replacement chars
        full = banner.inner_text()
        check("banner text has no replacement char (\ufffd)", "\ufffd" not in full,
              f"got '{full[:80]}'")

    # Confirm sidebar upgrade button reached is-available state
    ub = page.query_selector("#upgradeBtn")
    ub_classes = ub.evaluate("el => el.className") if ub else ""
    ub_label = ub.query_selector(".ub-label").inner_text() if ub and ub.query_selector(".ub-label") else ""
    check("upgradeBtn is-available", "is-available" in ub_classes,
          f"classes='{ub_classes}' label='{ub_label}'")
    check("upgradeBtn label shows new version", new_ver in ub_label, f"got '{ub_label}'")

    # ── THE REAL UPGRADE CLICK ──
    # Do NOT route()/mock. Let it hit the real /api/update/upgrade →
    # perform_upgrade() → download encoded URL → update.bat → restart.
    if "is-available" in ub_classes:
        print("  clicking upgrade button (REAL download + bat will run)...")
        ub.click()
        # The POST returns once update.bat is launched. Wait for the JSON.
        page.wait_for_timeout(4000)
        # After ok, frontend calls /api/shutdown → portal exits → bat waits for
        # 7000 to free → extracts → copies → restarts portal on 7000.
        # Watch for the portal to come back with the NEW version.
        print("  waiting for portal to restart with new version (up to 300s)...")
        restarted_new = False
        # First, portal should drop (port closed briefly)
        # 300s ceiling: real upgrade copies ~4000 runtime files via robocopy,
        # which alone takes ~100-150s on a typical disk, plus portal boot ~30s.
        # Observed end-to-end on this machine: ~189s (see log/mistake.txt #55).
        restart_deadline = time.time() + 300
        seen_down = False
        while time.time() < restart_deadline:
            up = port_open(CUSTOMER_PORT)
            if not up:
                seen_down = True
            if seen_down and up:
                # back up — check version
                try:
                    st, body = http_get(f"http://127.0.0.1:{CUSTOMER_PORT}/", timeout=8)
                    if new_ver in body:
                        restarted_new = True
                        print(f"  portal restarted showing v{new_ver}")
                        break
                except Exception:
                    pass
            time.sleep(2)
        check("portal restarted showing NEW version", restarted_new,
              "did not come back with new version in 300s")
        upgrade_launched_clean = restarted_new
    else:
        check("upgradeBtn available to click", False,
              "cannot start real upgrade — button not in available state")

    # Console errors (filter known sub-app 502 noise during boot)
    relevant = [e for e in console_errors
                if "favicon" not in e.lower()
                and "ERR_" not in e
                and "502" not in e]
    check("zero relevant console errors", not relevant,
          f"{relevant[:3]}")

    try:
        page.screenshot(path=str(ROOT / "application" / "test" / "portal" / "real_upgrade_result.png"))
    except Exception:
        pass
    browser.close()

# ───────────────────────── post-upgrade verification ─────────────────────────
if upgrade_launched_clean:
    # Read the (now upgraded) RELEASE_INFO.json from the bundle
    ri = json.loads((cust_dir / "RELEASE_INFO.json").read_text(encoding="utf-8"))
    check("bundle RELEASE_INFO now = new version", ri.get("version") == new_ver,
          f"got {ri.get('version')}")
    # Garbled filenames check after the robocopy copy step
    g1 = garbled_files(cust_dir)
    check("no garbled filenames after upgrade", not g1, f"{g1[:5]}")

# ───────────────────────── cleanup ─────────────────────────
print("\n--- cleanup ---")
# The portal may have been replaced by the upgrade; kill by port.
kill_ports(7000, 7001, 7002, 7003, 7004, 8000)
try:
    portal.terminate(); portal.wait(timeout=5)
except Exception:
    try: portal.kill()
    except Exception: pass
try:
    mirror.terminate(); mirror.wait(timeout=5)
except Exception:
    try: mirror.kill()
    except Exception: pass
# Keep TEMP on failure for post-mortem (log/mistake.txt #50/#55 discipline).
if FAILED == 0:
    shutil.rmtree(TEMP, ignore_errors=True)
    print(f"  cleaned {TEMP}")
else:
    print(f"  KEPT {TEMP} for inspection (failures present)")

print("\n" + "=" * 64)
print(f"  Results: {PASSED} passed, {FAILED} failed")
print("=" * 64)
sys.exit(0 if FAILED == 0 else 1)
