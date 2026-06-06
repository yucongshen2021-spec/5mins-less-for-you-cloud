"""Complete end-to-end update pipeline test.

Simulates the FULL customer journey:
  1. Build two versions (old + new)
  2. Start mirror server
  3. DEMO: verify download card shows latest version
  4. DEMO: verify download URL works
  5. RELEASE: extract old version, start it
  6. RELEASE: verify auto-check detects update
  7. RELEASE: click upgrade button
  8. RELEASE: verify new version starts
  9. RELEASE: verify user data preserved

Run before every release to guarantee update integrity.
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
BUILD_SCRIPT = PROJECT_ROOT / "tools" / "build_release.py"
MIRROR_SCRIPT = PROJECT_ROOT / "tools" / "serve_mirror.py"
PORTAL_APP = PROJECT_ROOT / "application" / "portal" / "app.py"
TEMP_ROOT = PROJECT_ROOT / "temp" / "test_e2e"

MIRROR_PORT = 8000
DEMO_PORT = 5000
RELEASE_PORT = 7000

TEST_VERSION_OLD = "0.0.0-e2e-old"
TEST_VERSION_NEW = "0.0.1-e2e-new"

PASSED = 0
FAILED = 0
SKIPPED = 0


def log(msg: str) -> None:
    print(f"  [{PASSED + FAILED + SKIPPED + 1}] {msg}", flush=True)


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"    PASS  {name}")
    else:
        FAILED += 1
        print(f"    FAIL  {name}" + (f" — {detail}" if detail else ""))


def skip(name: str, reason: str) -> None:
    global SKIPPED
    SKIPPED += 1
    print(f"    SKIP  {name} ({reason})")


def port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "e2e-test/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def http_post(url: str, data: dict, timeout: float = 10.0) -> tuple[int, dict]:
    import urllib.request
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "e2e-test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8"))


def run(cmd: list[str], cwd: Path = None, env: dict = None,
        timeout: float = 60.0) -> subprocess.Popen:
    return subprocess.Popen(
        cmd, cwd=str(cwd) if cwd else None,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env or os.environ,
    )


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


def wait_for_port(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(0.5)
    return False


# ============================================================================
# Phase 1: Build test versions
# ============================================================================

def phase1_build():
    log("Phase 1: Build test versions")

    # Check build script exists
    check("build_release.py exists", BUILD_SCRIPT.exists())

    # Clean old test zips
    for f in DIST_DIR.glob(f"*-{TEST_VERSION_OLD}.zip"):
        f.unlink()
    for f in DIST_DIR.glob(f"*-{TEST_VERSION_NEW}.zip"):
        f.unlink()

    # Save original RELEASE_INFO
    ri_path = PROJECT_ROOT / "RELEASE_INFO.json"
    original_ri = ri_path.read_text(encoding="utf-8") if ri_path.exists() else "{}"

    try:
        # Build OLD version
        ri_path.write_text(
            json.dumps({"version": TEST_VERSION_OLD.lstrip("v"),
                        "name": "test", "built_at": "2000-01-01T00:00:00Z"}),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT),
             "--version", TEST_VERSION_OLD,
             "--no-runtime"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        check("Build old version", result.returncode == 0,
              result.stderr.strip()[-200:] if result.returncode != 0 else "")

        # Build NEW version
        ri_path.write_text(
            json.dumps({"version": TEST_VERSION_NEW.lstrip("v"),
                        "name": "test", "built_at": "2000-01-02T00:00:00Z"}),
            encoding="utf-8",
        )
        result = subprocess.run(
            [sys.executable, str(BUILD_SCRIPT),
             "--version", TEST_VERSION_NEW,
             "--no-runtime"],
            cwd=str(PROJECT_ROOT),
            capture_output=True, text=True, encoding="utf-8", timeout=120,
        )
        check("Build new version", result.returncode == 0,
              result.stderr.strip()[-200:] if result.returncode != 0 else "")

        # Verify both zips exist
        old_zips = list(DIST_DIR.glob(f"*-{TEST_VERSION_OLD}.zip"))
        new_zips = list(DIST_DIR.glob(f"*-{TEST_VERSION_NEW}.zip"))
        check("Old zip exists", len(old_zips) > 0)
        check("New zip exists", len(new_zips) > 0)

    finally:
        ri_path.write_text(original_ri, encoding="utf-8")

    return True


# ============================================================================
# Phase 2: Mirror server
# ============================================================================

def phase2_mirror():
    log("Phase 2: Mirror server")

    kill_port(MIRROR_PORT)
    proc = run([sys.executable, str(MIRROR_SCRIPT), "--port", str(MIRROR_PORT),
                "--dist", str(DIST_DIR)])

    ok = wait_for_port(MIRROR_PORT, timeout=15)
    check("Mirror starts on port 8000", ok)

    if not ok:
        return None

    # Verify manifest
    status, body = http_get(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest")
    check("Mirror manifest returns 200", status == 200, f"got {status}")
    data = json.loads(body)
    check("Mirror manifest ok=True", data.get("ok") is True)
    check("Mirror version is new", data.get("version") == TEST_VERSION_NEW.lstrip("v"),
          f"got {data.get('version')}")
    import re
    check("Mirror version is clean semver",
          bool(re.match(r"^\d+\.\d+\.\d+", data.get("version", ""))),
          f"got '{data.get('version')}'")
    check("Mirror has download_url", bool(data.get("download_url")))

    return proc


# ============================================================================
# Phase 3: Demo download flow
# ============================================================================

def phase3_demo():
    log("Phase 3: Demo download flow")

    kill_port(DEMO_PORT)
    env = {**os.environ, "NO_BROWSER": "1"}
    proc = run([sys.executable, str(PORTAL_APP)],
               cwd=PORTAL_APP.parent, env=env)

    ok = wait_for_port(DEMO_PORT, timeout=45)
    check("Demo portal starts on 5000", ok)

    if not ok:
        proc.kill()
        return None

    # Check download endpoint
    status, body = http_get(f"http://127.0.0.1:{DEMO_PORT}/api/download/latest")
    check("Demo download returns 200", status == 200)
    data = json.loads(body)
    check("Demo download available=True",
          data.get("available") is True, f"got {data}")
    check("Demo shows latest version",
          data.get("version") == TEST_VERSION_NEW.lstrip("v"),
          f"expected {TEST_VERSION_NEW}, got {data.get('version')}")
    check("Demo has filename", bool(data.get("filename")))

    # Check demo HTML has dlCard
    status, body = http_get(f"http://127.0.0.1:{DEMO_PORT}/")
    check("Demo page returns 200", status == 200)
    check("Demo has dlCard", 'id="dlCard"' in body)
    check("Demo has NO upgradeBtn", 'id="upgradeBtn"' not in body)
    check("Demo has NO updateBanner", 'id="updateBanner"' not in body)

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    kill_port(DEMO_PORT)

    return True


# ============================================================================
# Phase 4: Release update check
# ============================================================================

def phase4_release_check():
    log("Phase 4: Release update check (Playwright)")

    from playwright.sync_api import sync_playwright

    kill_port(RELEASE_PORT)
    env = {**os.environ, "RELEASE_MODE": "1", "NO_BROWSER": "1"}

    proc = run([sys.executable, str(PORTAL_APP)],
               cwd=PORTAL_APP.parent, env=env)

    ok = wait_for_port(RELEASE_PORT, timeout=45)
    check("Release portal starts on 7000", ok)

    if not ok:
        proc.kill()
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(f"http://127.0.0.1:{RELEASE_PORT}")
        page.wait_for_load_state("networkidle")

        # Wait for auto-check
        log("  Waiting for auto update check (8s)...")
        page.wait_for_timeout(8000)

        # Check banner
        banner = page.query_selector("#updateBanner")
        check("Banner element exists", banner is not None)
        if banner:
            display = banner.evaluate("el => window.getComputedStyle(el).display")
            if display != "none":
                ver = page.query_selector("#updateBannerVer")
                check("Banner visible with version",
                      ver is not None and ver.inner_text() != "",
                      f"version text: '{ver.inner_text() if ver else 'N/A'}'")

        # Check upgrade button
        btn = page.query_selector("#upgradeBtn")
        check("Upgrade button exists", btn is not None)
        if btn:
            classes = btn.evaluate("el => el.className")
            label_el = btn.query_selector(".ub-label")
            label = label_el.inner_text() if label_el else ""
            check("Button not in error state", "is-error" not in classes,
                  f"label='{label}' classes='{classes}'")

        # Check header manual button
        manual_btn = page.query_selector("#btnCheckUpdate")
        check("Manual check button exists", manual_btn is not None)

        # Console error check
        relevant = [e for e in errors if "ERR_" not in e and "favicon" not in e.lower()]
        check("No console errors", len(relevant) == 0,
              f"errors: {relevant[:3]}" if relevant else "")

        browser.close()

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    kill_port(RELEASE_PORT)

    return True


# ============================================================================
# Phase 5: Full upgrade + data preservation
# ============================================================================

def phase5_upgrade_and_preserve():
    log("Phase 5: Full upgrade + data preservation")

    # Find old zip
    old_zips = sorted(
        DIST_DIR.glob(f"*-{TEST_VERSION_OLD}.zip"),
        key=lambda p: p.stat().st_mtime,
    )
    if not old_zips:
        skip("Upgrade test", "old zip not found")
        return None

    old_zip = old_zips[0]
    extract_dir = TEMP_ROOT / "upgrade_test_client"
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    # Extract old version
    log("  Extracting old version...")
    with zipfile.ZipFile(old_zip) as zf:
        zf.extractall(extract_dir)

    # Find the bundle directory inside (could be "test" or "test-release")
    bundle_dirs = [d for d in extract_dir.iterdir() if d.is_dir()]
    if not bundle_dirs:
        check("Bundle dir found", False, f"no dirs in {extract_dir}")
        return None

    bundle_dir = bundle_dirs[0]
    log(f"  Bundle dir: {bundle_dir.name}")

    app_py = bundle_dir / "application" / "portal" / "app.py"
    check("app.py exists in extracted zip", app_py.is_file())

    # Create test user data
    log("  Creating test user data...")
    test_file = bundle_dir / "test_user_data.txt"
    test_file.write_text("This is user test data that must survive upgrade.", encoding="utf-8")

    workspace_dir = bundle_dir / "application" / "all_in_one - cc" / "data" / "editor_workspace"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    (workspace_dir / "test_template.json").write_text(
        '{"name":"user template","content":"test"}', encoding="utf-8"
    )

    # Set RELEASE_INFO to old version for testing
    ri = bundle_dir / "RELEASE_INFO.json"
    ri.write_text(json.dumps({
        "version": TEST_VERSION_OLD.lstrip("v"),
        "name": "test", "built_at": "2000-01-01T00:00:00Z",
    }), encoding="utf-8")

    # Write mirror config
    cfg = bundle_dir / "application" / "portal" / "update_config.json"
    cfg.write_text(json.dumps({
        "mirror_urls": [f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest"],
        "mirror_url": "",
        "timeout_seconds": 5,
        "cache_ttl_seconds": 0,  # No caching for test
        "user_agent": "e2e-test",
    }, indent=2), encoding="utf-8")

    # Start the extracted portal
    log("  Starting extracted portal...")
    kill_port(RELEASE_PORT)
    env = {**os.environ, "RELEASE_MODE": "1", "NO_BROWSER": "1"}

    # Try using bundled python if available, else system python
    python_exe = bundle_dir / "runtime" / "python" / "python.exe"
    if python_exe.is_file():
        python_cmd = str(python_exe)
        log(f"  Using bundled Python: {python_cmd}")
    else:
        python_cmd = sys.executable
        log(f"  Using system Python: {python_cmd}")

    proc = run([python_cmd, str(app_py)],
               cwd=app_py.parent, env=env)

    ok = wait_for_port(RELEASE_PORT, timeout=60)
    check("Extracted portal starts on 7000", ok)

    if not ok:
        proc.kill()
        return None

    # Check update detection
    log("  Checking update detection...")
    time.sleep(5)  # Allow sub-apps to start
    status, body = http_get(
        f"http://127.0.0.1:{RELEASE_PORT}/api/update/check?force=1",
        timeout=15.0,
    )
    data = json.loads(body) if status == 200 else {}
    check("Update check returns 200", status == 200)
    check("Update check status=ok", data.get("status") == "ok",
          f"got status={data.get('status')}")
    check("Update check has_update=True",
          data.get("has_update") is True,
          f"got {data.get('has_update')}, local={data.get('local_version')}, remote={data.get('remote_version')}")
    check("Update check has download_url",
          bool(data.get("download_url")),
          f"download_url={data.get('download_url', 'N/A')[:80]}")

    # Test upgrade API
    log("  Testing upgrade API...")
    if data.get("download_url"):
        durl = data["download_url"]
        status, result = http_post(
            f"http://127.0.0.1:{RELEASE_PORT}/api/update/upgrade",
            {"download_url": durl},
            timeout=30.0,
        )
        check("Upgrade API returns 200", status == 200, f"got {status}")
        check("Upgrade API ok=True",
              result.get("ok") is True,
              f"got {json.dumps(result, indent=2)}")
        check("Upgrade stage=launched",
              result.get("stage") == "launched",
              f"got {result.get('stage')}")

        # Wait for upgrade to complete
        log("  Waiting for upgrade to complete...")
        time.sleep(15)

        # Check if portal restarted
        restarted = wait_for_port(RELEASE_PORT, timeout=30)
        if restarted:
            check("Portal restarted after upgrade", True)

            # Verify data preserved
            log("  Verifying data preservation...")
            if test_file.exists():
                content = test_file.read_text(encoding="utf-8")
                check("User test file preserved",
                      "must survive upgrade" in content,
                      f"content: {content[:50]}")
            else:
                check("User test file preserved", False, "file missing after upgrade")

            if (workspace_dir / "test_template.json").exists():
                check("Workspace data preserved", True)
            else:
                check("Workspace data preserved", False, "workspace file missing")

            # Verify new version running
            try:
                status, body = http_get(
                    f"http://127.0.0.1:{RELEASE_PORT}/api/update/check?force=1",
                    timeout=10.0,
                )
                if status == 200:
                    new_data = json.loads(body)
                    check("New version is installed",
                          new_data.get("local_version") == TEST_VERSION_NEW.lstrip("v"),
                          f"local={new_data.get('local_version')}, "
                          f"expected={TEST_VERSION_NEW.lstrip('v')}")
            except Exception:
                check("New version responding", False, "portal not reachable")

        else:
            check("Portal restarted after upgrade", False,
                  "portal did not come back online")
    else:
        skip("Upgrade test", "no download_url in check response")

    # Cleanup
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    kill_port(RELEASE_PORT)

    return True


# ============================================================================
# Phase 6: Cleanup
# ============================================================================

def phase6_cleanup():
    log("Phase 6: Cleanup")

    # Kill all processes
    for port in [MIRROR_PORT, DEMO_PORT, RELEASE_PORT]:
        kill_port(port)

    # Remove test zips
    for f in DIST_DIR.glob(f"*-{TEST_VERSION_OLD}.zip"):
        f.unlink()
        check(f"Removed {f.name}", True)
    for f in DIST_DIR.glob(f"*-{TEST_VERSION_NEW}.zip"):
        f.unlink()
        check(f"Removed {f.name}", True)

    # Remove temp directory
    if TEMP_ROOT.exists():
        shutil.rmtree(TEMP_ROOT)
        check("Removed temp directory", True)


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 60)
    print("  End-to-End Update Pipeline Test")
    print("=" * 60)
    print(f"  Old version: {TEST_VERSION_OLD}")
    print(f"  New version: {TEST_VERSION_NEW}")
    print(f"  Mirror port: {MIRROR_PORT}")
    print(f"  Release port: {RELEASE_PORT}")
    print(f"  Demo port: {DEMO_PORT}")
    print()

    mirror_proc = None

    try:
        # Phase 1-2: Build + Mirror
        if not phase1_build():
            print("\n  ABORTED: Build failed")
            return 1

        mirror_proc = phase2_mirror()
        if mirror_proc is None:
            print("\n  ABORTED: Mirror failed")
            return 1

        # Phase 3: Demo
        phase3_demo()

        # Phase 4: Release check
        phase4_release_check()

        # Phase 5: Upgrade + data preservation
        phase5_upgrade_and_preserve()

    finally:
        # Cleanup
        if mirror_proc:
            mirror_proc.terminate()
        phase6_cleanup()

    print()
    print("=" * 60)
    total = PASSED + FAILED + SKIPPED
    print(f"  Results: {PASSED} passed, {FAILED} failed, {SKIPPED} skipped ({total} total)")
    if FAILED == 0:
        print("  STATUS: ALL CHECKS PASSED")
    else:
        print(f"  STATUS: {FAILED} FAILURES")
    print("=" * 60)

    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
