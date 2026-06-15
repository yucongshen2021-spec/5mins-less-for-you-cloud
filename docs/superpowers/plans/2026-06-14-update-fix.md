# Release Update Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix online update garbled filenames, incomplete updates; build v1.1.18; end-to-end Playwright verification; solidify update logic.

**Architecture:** Fix encoding issues in upgrade URL/path handling, add missing shutdown route, strengthen robocopy error handling, extend port wait timeout, fix start_all.bat port list. Then build v1.1.18, run E2E Playwright test simulating real customer update.

---

### Task 1: Write failing Playwright E2E test

**Files:**
- Create: `application/test/portal/test_update_e2e.py`

- [x] **Step 1: Write the E2E test that simulates a real customer update**

```python
"""E2E: customer downloads v1.1.17, installs, checks for v1.1.18 update, upgrades, verifies."""
from playwright.sync_api import sync_playwright
import subprocess, requests, time, json, zipfile, tempfile, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
MIRROR_PORT = 8000
RELEASE_PORT = 7000

def test_customer_update():
    """
    Simulates a real customer:
    1. Extract v1.1.17 zip to temp directory
    2. Start mirror serving dist/ (with v1.1.18 available)
    3. Start v1.1.17 portal on port 7000
    4. Open browser, verify portal shows v1.1.17
    5. Wait for update check — should show v1.1.18 available
    6. Click upgrade button
    7. Wait for upgrade to complete (portal restarts)
    8. Verify portal now shows v1.1.18
    9. Verify NO garbled filenames, NO incomplete files
    """
    # Find v1.1.17 and v1.1.18 zips
    zips = sorted(DIST.glob("帮你节省5分钟-*.zip"), key=lambda p: p.stat().st_mtime)
    old_zip = None; new_zip = None
    for z in zips:
        if "1.1.17" in z.name: old_zip = z
        if "1.1.18" in z.name: new_zip = z
    assert old_zip and new_zip, f"Need both 1.1.17 and 1.1.18 zips in dist/. Found: {[z.name for z in zips]}"

    print(f"Old: {old_zip.name} ({old_zip.stat().st_size} bytes)")
    print(f"New: {new_zip.name} ({new_zip.stat().st_size} bytes)")

    # 1. Extract v1.1.17 to temp (simulating customer download)
    customer_dir = Path(tempfile.mkdtemp(prefix="customer_"))
    print(f"Customer dir: {customer_dir}")
    with zipfile.ZipFile(old_zip, 'r') as zf:
        zf.extractall(customer_dir)
    
    # Find extracted bundle directory
    extracted_dirs = [d for d in customer_dir.iterdir() if d.is_dir()]
    assert len(extracted_dirs) == 1, f"Expected 1 directory, got {len(extracted_dirs)}"
    bundle_dir = extracted_dirs[0]
    print(f"Bundle dir: {bundle_dir.name}")
    
    # Check NO garbled characters in extracted names
    garbled = []
    for p in bundle_dir.rglob("*"):
        try:
            p.name.encode('gbk')
        except UnicodeEncodeError:
            garbled.append(str(p))
    assert not garbled, f"Found garbled filenames: {garbled}"

    # 2. Start mirror
    mirror = subprocess.Popen(
        ["py", str(ROOT / "tools" / "serve_mirror.py"), "--port", str(MIRROR_PORT), "--dist", str(DIST)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    time.sleep(2)
    
    # Verify mirror is running
    r = requests.get(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest", timeout=5)
    assert r.json()["ok"], f"Mirror not working: {r.json()}"
    manifest = r.json()
    print(f"Mirror manifest: version={manifest.get('version')}, download_url={manifest.get('download_url')}")

    # 3. Start portal
    python_exe = bundle_dir / "runtime" / "python" / "python.exe"
    portal = subprocess.Popen(
        [str(python_exe), "application/portal/app.py"],
        cwd=str(bundle_dir), env={**dict(subprocess.os.environ), "RELEASE_MODE": "1"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    
    # Wait for portal to start
    for _ in range(30):
        try:
            r = requests.get(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=3)
            if r.status_code == 200:
                break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("Portal did not start within 60s")

    errors = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        
        # 4. Open portal
        page.goto(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=15000)
        page.wait_for_timeout(3000)
        
        # Check version display (should be v1.1.17)
        content = page.content()
        if "1.1.17" not in content:
            errors.append("Portal doesn't show v1.1.17")
        print(f"Portal loaded, v1.1.17 visible: {'1.1.17' in content}")
        
        # 5. Wait for auto update check (5s after load) + manual check
        page.wait_for_timeout(8000)
        
        # Check for upgrade button state change
        upgrade_btn = page.query_selector("#upgradeBtn")
        if upgrade_btn:
            btn_text = upgrade_btn.text_content()
            btn_classes = upgrade_btn.get_attribute("class") or ""
            print(f"Upgrade button: text={btn_text}, classes={btn_classes}")
            
            # Should show update available
            if "is-available" not in btn_classes:
                # Try manual check
                check_btn = page.query_selector("#btnCheckUpdate")
                if check_btn:
                    check_btn.click()
                    page.wait_for_timeout(3000)
                    btn_classes = upgrade_btn.get_attribute("class") or ""
                    print(f"After manual check: classes={btn_classes}")
            
            if "is-available" not in btn_classes:
                errors.append(f"Update not detected. Button state: {btn_classes}")
        
        # 6. Check for update banner
        banner = page.query_selector("#updateBanner")
        if banner:
            banner_display = banner.evaluate("el => getComputedStyle(el).display")
            print(f"Banner display: {banner_display}")
        
        # 7. Click upgrade if available
        if upgrade_btn and "is-available" in (upgrade_btn.get_attribute("class") or ""):
            print("Clicking upgrade...")
            upgrade_btn.click()
            page.wait_for_timeout(2000)
            
            # Check for toast message
            toast_text = page.text_content("body")
            if "升级已启动" in toast_text or "重启" in toast_text:
                print("Upgrade launched toast visible")
            else:
                errors.append("No upgrade launch confirmation visible")
        
        # 8. Wait for portal to restart (up to 60s)
        print("Waiting for portal to restart...")
        for _ in range(60):
            try:
                r = requests.get(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=3)
                if r.status_code == 200:
                    time.sleep(2)
                    break
            except Exception:
                time.sleep(2)
        else:
            errors.append("Portal did not restart within 120s")
        
        # 9. Reload page and verify new version
        page.goto(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=15000)
        page.wait_for_timeout(3000)
        content = page.content()
        if "1.1.18" in content:
            print("SUCCESS: Portal shows v1.1.18 after upgrade")
        else:
            errors.append(f"Portal doesn't show v1.1.18 after upgrade. Content snippet: {content[:200]}")
        
        # 10. Check for garbled files in the bundle
        garbled_after = []
        for p in bundle_dir.rglob("*"):
            try:
                p.name.encode('gbk')
            except UnicodeEncodeError:
                garbled_after.append(str(p.relative_to(bundle_dir)))
        if garbled_after:
            errors.append(f"Garbled files after upgrade: {garbled_after}")
        else:
            print("No garbled files after upgrade")
        
        browser.close()
    
    # Cleanup
    portal.terminate(); portal.wait(timeout=5)
    mirror.terminate(); mirror.wait(timeout=5)
    shutil.rmtree(customer_dir, ignore_errors=True)
    
    if errors:
        print(f"\nFAIL: {len(errors)} error(s)")
        for e in errors: print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nPASS: Customer update E2E successful")

if __name__ == "__main__":
    import sys
    test_customer_update()
```

- [x] **Step 2: Run the test — expect FAIL**

```bash
py application/test/portal/test_update_e2e.py
```
Expected: FAIL — no v1.1.18 zip exists yet.

---

### Task 2: Build demo v1.1.18

- [x] **Step 1: Build v1.1.18 on main branch**

```bash
git checkout main
py tools/build_release.py --version 1.1.18 --mirror-url http://192.168.72.219:8000/api/update/manifest
```

This creates `dist/帮你节省5分钟-1.1.18.zip`.

- [x] **Step 2: Verify zip contents**

```bash
py tools/_verify_zip.py dist/帮你节省5分钟-1.1.18.zip 1.1.18
```

Expected: ALL CHECKS PASSED

---

### Task 3: Fix Update Issues

- [x] **Step 1: Add `/api/shutdown` route to portal app.py**

At `application/portal/app.py`, add after the upgrade route:

```python
@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    """Gracefully shutdown portal (called by frontend after upgrade launch)."""
    import signal
    import os as _os
    def _shutdown():
        import time as _time
        _time.sleep(0.5)
        _os.kill(_os.getpid(), signal.SIGTERM)
    import threading as _threading
    _threading.Thread(target=_shutdown, daemon=True).start()
    return jsonify({"ok": True})
```

- [x] **Step 2: Fix upgrade.py — robust extraction with encoding handling**

In `application/portal/upgrade.py`, update the `UPDATE_BAT_TEMPLATE`:

Replace the PowerShell extraction step with cmd-native extraction to avoid encoding issues:
```bat
REM Step 4: Extract using PowerShell with UTF-8 handling
powershell -NoProfile -Command ^
  "[Console]::OutputEncoding = [Text.Encoding]::UTF8; ^
   Add-Type -AssemblyName System.IO.Compression.FileSystem; ^
   [System.IO.Compression.ZipFile]::ExtractToDirectory('__update__.zip', '__update_tmp__')"
```

- [x] **Step 3: Fix start_all.bat port kill list**

Update `start_all.bat` line ~20 to include release ports:
```bat
REM Kill stale processes
for %%p in (5003 5002 5001 5004 5000 7003 7002 7001 7004 7000) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
```

- [x] **Step 4: Fix update bat — increase port wait timeout + add file unlock**

Change 20s port wait to 30s. Add file unlock before robocopy:
```bat
REM Step 1: Wait for portal exit (30s)
set /a _t=0
:_loop
set /a _t+=1
for %%p in (7000 7001 7002 7003 7004) do (
    netstat -ano | findstr ":%%p " | findstr "LISTENING" >nul 2>&1
    if errorlevel 1 goto :_port_free
)
if %_t% geq 30 goto :_force_kill
timeout /t 1 >nul
goto :_loop
:_force_kill
REM Force kill remaining processes
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
:_port_free
timeout /t 3 >nul
REM Step 4: Unlock files before robocopy
powershell -NoProfile -Command ^
  "Get-ChildItem '__update_tmp__' -Recurse | ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }"
```

- [x] **Step 5: Fix upgrade.py — verify robocopy success**

After robocopy step, add explicit verification:
```bat
REM Verify RELEASE_INFO.json was copied
if not exist "RELEASE_INFO.json" (
    echo ERROR: RELEASE_INFO.json missing after copy
    set ERR=1
)
```

---

### Task 4: Run E2E test and iterate

- [x] **Step 1: Start fresh mirror and run E2E test**

```bash
# Kill existing processes
taskkill /F /IM python.exe /FI "WINDOWTITLE eq *serve_mirror*" 2>nul
# Start mirror
start "mirror" py tools/serve_mirror.py --port 8000 --dist dist
# Wait for mirror
timeout /t 2
# Run test
py application/test/portal/test_update_e2e.py
```

- [x] **Step 2: If test fails, fix issues and re-run**

Check test output for specific failures. Fix each issue one at a time.

- [x] **Step 3: Run test again expecting PASS**

```bash
py application/test/portal/test_update_e2e.py
```
Expected: PASS — Customer update E2E successful

---

### Task 5: Solidify — add to CI/pre-release checklist

- [x] **Step 1: Add E2E test to release checklist in docs/RELEASE.md**

```markdown
## 发版前置条件

- [x] `py application/test/portal/test_update_e2e.py` 通过（模拟客户在线更新）
```

- [x] **Step 2: Commit all changes**

```bash
git add -A
git commit -m "fix: robust update — fix encoding, add shutdown route, extend wait, E2E test"
```

- [x] **Step 3: Rebuild v1.1.18 with fixes included**

```bash
py tools/build_release.py --version 1.1.18 --mirror-url http://192.168.72.219:8000/api/update/manifest
```

---
