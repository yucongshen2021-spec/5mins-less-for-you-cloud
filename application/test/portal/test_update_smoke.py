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
from pathlib import Path

# Ensure we can import from the test/portal package
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _update_utils import (
    PROJECT_DIR, MIRROR_PORT, CUSTOMER_PORT_BASE, BUNDLE_NAME,
    port_open, kill_port, kill_ports,
    mirror_url, mirror_ok, fetch_manifest,
    http_get, html_contains_selectors,
    unzip, replace_config, find_content_root, _force_rmtree,
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
    # Check raw URL (before decoding) — it should be percent-encoded
    for ch in url:
        if '\u4e00' <= ch <= '\u9fff' or '\u3000' <= ch <= '\u303f':
            _fail(f"Download URL contains raw Chinese char '{ch}': {url[:120]}")
            return
    _ok("No raw Chinese in download URL")


def test_customer_check_update() -> None:
    """Extract oldest zip, start portal, call /api/update/check?force=1."""
    print("\n[3/5] Customer check-update")
    zips = dist_zips()
    if len(zips) < 2:
        _fail(f"Need >= 2 zips in dist/, found {len(zips)}")
        return
    old_zip = zips[0]
    old_ver = read_zip_version(old_zip)
    _ok(f"oldest zip: {old_zip.name} (v{old_ver})")

    tmp = Path(tempfile.mkdtemp(prefix="smoke_"))
    try:
        # Extract
        extract_dir = tmp / "customer"
        unzip(old_zip, extract_dir)
        content_root = find_content_root(extract_dir)

        # Inject mirror config + port
        replace_config(extract_dir, mirror_host="127.0.0.1", customer_port=CUSTOMER_PORT_BASE)

        # Kill any stale processes
        kill_port(CUSTOMER_PORT_BASE)

        # Start portal
        python_exe = content_root / "runtime" / "python" / "python.exe"
        app_py = content_root / "application" / "portal" / "app.py"
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
        # Wait for HTTP server to actually respond
        _ok("portal started, waiting for HTTP...")
        deadline = time.time() + 30
        portal_ready = False
        while time.time() < deadline:
            s, _ = http_get(f"http://127.0.0.1:{CUSTOMER_PORT_BASE}/", timeout=5.0)
            if s == 200:
                portal_ready = True
                break
            time.sleep(1)
        if not portal_ready:
            _fail("Portal HTTP not responding within 30s")
            proc.terminate()
            return
        _ok("portal HTTP ready")

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
        try:
            http_get(f"http://127.0.0.1:{CUSTOMER_PORT_BASE}/api/shutdown", timeout=5.0)
            proc.wait(timeout=10)
        except Exception:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
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
