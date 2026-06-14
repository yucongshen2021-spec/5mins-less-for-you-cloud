"""E2E: customer installs older version, checks for update, upgrades to newer version.

Simulates real customer flow:
  1. Extract old zip to temp (customer install)
  2. Start mirror serving dist/ (with newer zip)
  3. Start portal in RELEASE_MODE on port 7000
  4. Verify old version shown
  5. Check for update → should find newer version
  6. Click upgrade button
  7. Wait for restart with new version
  8. Verify no garbled filenames
"""
from playwright.sync_api import sync_playwright
import subprocess, requests, time, zipfile, tempfile, shutil, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "dist"
MIRROR_PORT = 8000
RELEASE_PORT = 7000


def main():
    zips = sorted(DIST.glob("帮你节省5分钟-*.zip"), key=lambda p: p.stat().st_mtime)
    assert len(zips) >= 2, f"Need >=2 zips in dist/, found {len(zips)}: {[z.name for z in zips]}"
    old_zip = zips[-2]
    new_zip = zips[-1]
    old_ver = old_zip.name.replace("帮你节省5分钟-", "").replace(".zip", "")
    new_ver = new_zip.name.replace("帮你节省5分钟-", "").replace(".zip", "")
    print(f"Testing update: {old_ver} -> {new_ver}")

    # 1. Extract old version
    cust = Path(tempfile.mkdtemp(prefix="cust_"))
    print(f"Extracting {old_zip.name}")
    with zipfile.ZipFile(old_zip, 'r') as zf:
        zf.extractall(cust)
    dirs = [d for d in cust.iterdir() if d.is_dir()]
    assert len(dirs) == 1, f"Bundle dirs: {dirs}"
    bundle = dirs[0]

    # Check garbled after extract
    garbled = []
    for p in bundle.rglob("*"):
        if not p.exists(): continue
        try: p.name.encode('gbk')
        except UnicodeEncodeError: garbled.append(str(p.relative_to(bundle)))
    if garbled: print(f"WARN garbled after extract: {garbled}")

    # 2. Start mirror
    mirror = subprocess.Popen(
        ["py", str(ROOT / "tools" / "serve_mirror.py"), "--port", str(MIRROR_PORT),
         "--dist", str(DIST)],
        cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(3)
    r = requests.get(f"http://127.0.0.1:{MIRROR_PORT}/api/update/manifest", timeout=5)
    assert r.json()["ok"], f"Mirror: {r.json()}"
    print(f"Mirror: v{r.json().get('version')}")

    # 3. Start portal
    env = {**dict(os.environ), "RELEASE_MODE": "1"}
    py = str(bundle / "runtime" / "python" / "python.exe")
    portal = subprocess.Popen(
        [py, "application/portal/app.py"], cwd=str(bundle),
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    for i in range(40):
        try:
            if requests.get(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=3).status_code == 200:
                break
        except Exception: time.sleep(2)
    else: raise RuntimeError("Portal didn't start within 80s")

    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=15000)
        page.wait_for_timeout(10000)  # Wait for auto-check

        body = page.text_content("body")
        print(f"Old version visible: {old_ver in body}")

        btn = page.query_selector("#upgradeBtn")
        if not btn:
            errors.append("No #upgradeBtn")
        else:
            cls = btn.get_attribute("class") or ""
            print(f"Upgrade btn: {cls}")

            if "is-available" not in cls:
                # Manual check
                mbtn = page.query_selector("#btnCheckUpdate")
                if mbtn:
                    mbtn.click()
                    page.wait_for_timeout(5000)
                    cls = btn.get_attribute("class") or ""
                    print(f"After manual check: {cls}")

            if "is-available" in cls:
                print("Clicking upgrade...")
                btn.click()
                page.wait_for_timeout(3000)
            else:
                errors.append(f"Update not available. State={cls}")

        # 5. Wait for restart
        print("Waiting for restart...")
        for i in range(90):
            try:
                r = requests.get(f"http://127.0.0.1:{RELEASE_PORT}/", timeout=3)
                if r.status_code == 200 and new_ver in r.text:
                    print(f"Restarted with {new_ver}!")
                    break
            except Exception: time.sleep(2)
        else: errors.append("Didn't restart with new version")

        # 6. Garbled check
        g2 = []
        for p in bundle.rglob("*"):
            if not p.exists(): continue
            try: p.name.encode('gbk')
            except UnicodeEncodeError: g2.append(str(p.relative_to(bundle)))
        if g2: errors.append(f"Garbled after upgrade: {g2}")
        else: print("No garbled files")

        browser.close()

    portal.terminate(); portal.wait(timeout=5)
    mirror.terminate(); mirror.wait(timeout=5)
    shutil.rmtree(cust, ignore_errors=True)

    if errors:
        print(f"\nFAIL: {len(errors)} errors")
        for e in errors: print(f"  - {e}")
        sys.exit(1)
    print(f"\nPASS: {old_ver} -> {new_ver}")


if __name__ == "__main__":
    main()
