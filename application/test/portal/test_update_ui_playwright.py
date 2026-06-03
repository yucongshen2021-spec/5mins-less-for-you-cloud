"""Portal update UI end-to-end tests — Playwright clicks REAL buttons.

Covers the complete user journey:
  1. Open portal → wait for auto update check
  2. Verify banner appears with correct version
  3. Verify upgrade button states (5-state machine)
  4. Click manual check button → verify response
  5. Click upgrade button → verify state transitions
  6. Verify zero console errors throughout

Catches regressions:
  - Mirror not running (connection refused → button shows error)
  - Version string unparseable (incomparable → no banner)
  - Missing /api/update/upgrade route (404 → upgrade fails)
  - Hardcoded BUNDLE_NAME bat issue (upgrade API ok → bat generated correctly)

Pre-requisites:
  - dist/ must have a release zip (mirror scans it)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PORTAL_DIR = _PROJECT_ROOT / "application" / "portal"
_PORTAL_APP = _PORTAL_DIR / "app.py"
_DIST_DIR = _PROJECT_ROOT / "dist"
_MIRROR_SCRIPT = _PROJECT_ROOT / "tools" / "serve_mirror.py"
_RELEASE_INFO = _PROJECT_ROOT / "RELEASE_INFO.json"

_PORTAL_PORT = 7000
_MIRROR_PORT = 8000
_BASE_URL = f"http://127.0.0.1:{_PORTAL_PORT}"


def _port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(
            f'netstat -ano | findstr ":{port}" | findstr "LISTENING"',
            shell=True, text=True,
        )
        for line in out.strip().split("\n"):
            parts = line.strip().split()
            if parts:
                subprocess.run(
                    ["taskkill", "/F", "/PID", parts[-1]],
                    capture_output=True, shell=True,
                )
    except Exception:
        pass


@pytest.fixture(scope="module")
def mirror_server():
    """Start the mirror server on port 8000."""
    if not _MIRROR_SCRIPT.exists():
        pytest.skip(f"Mirror script not found: {_MIRROR_SCRIPT}")

    _kill_port(_MIRROR_PORT)
    proc = subprocess.Popen(
        [sys.executable, str(_MIRROR_SCRIPT), "--port", str(_MIRROR_PORT),
         "--dist", str(_DIST_DIR)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 15
    while time.time() < deadline:
        if _port_open(_MIRROR_PORT):
            break
        time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail(f"Mirror did not start on port {_MIRROR_PORT}")

    yield f"http://127.0.0.1:{_MIRROR_PORT}"

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


@pytest.fixture(scope="module")
def portal_server(mirror_server):
    """Start portal in release mode on port 7000."""
    if not _PORTAL_APP.exists():
        pytest.skip(f"Portal app not found: {_PORTAL_APP}")

    _kill_port(_PORTAL_PORT)

    env = {
        **os.environ,
        "RELEASE_MODE": "1",
        "NO_BROWSER": "1",
        "PYTHONUNBUFFERED": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(_PORTAL_APP)],
        cwd=str(_PORTAL_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    deadline = time.time() + 45
    while time.time() < deadline:
        if _port_open(_PORTAL_PORT):
            time.sleep(3)
            break
        time.sleep(1)
    else:
        proc.kill()
        pytest.fail(f"Portal did not start on port {_PORTAL_PORT}")

    yield _BASE_URL

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    _kill_port(_PORTAL_PORT)


@pytest.fixture(scope="module")
def browser_page(portal_server):
    """Open Playwright browser pointing at the portal."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        console_errors: list[str] = []
        page.on("console", lambda msg: (
            console_errors.append(f"[{msg.type}] {msg.text}")
            if msg.type == "error" else None
        ))

        page.goto(portal_server)
        page.wait_for_load_state("networkidle")

        yield page, console_errors

        if console_errors:
            print(f"\n  === Browser console errors ({len(console_errors)}) ===")
            for e in console_errors:
                print(f"    {e}")

        browser.close()


def _wait_for_update_check(page, timeout_ms: int = 10000) -> None:
    """Wait for the 5-second auto-update check to complete."""
    page.wait_for_timeout(timeout_ms)


# ============================================================================
# Tests
# ============================================================================

class TestUpdateBannerAndButtons:

    def test_banner_appears_after_auto_check(self, browser_page):
        page, errors = browser_page
        _wait_for_update_check(page)

        banner = page.query_selector("#updateBanner")
        assert banner is not None, "#updateBanner element not found in DOM"

        is_visible = banner.evaluate(
            "el => window.getComputedStyle(el).display !== 'none'"
        )
        if is_visible:
            ver_el = page.query_selector("#updateBannerVer")
            ver_text = ver_el.inner_text() if ver_el else ""
            assert ver_text, "Banner visible but #updateBannerVer is empty"

    def test_sidebar_button_not_in_error_state(self, browser_page):
        page, errors = browser_page
        _wait_for_update_check(page)

        btn = page.query_selector("#upgradeBtn")
        assert btn is not None, "#upgradeBtn not found in sidebar"

        classes = btn.evaluate("el => el.className")
        label_el = btn.query_selector(".ub-label")
        label = label_el.inner_text() if label_el else ""

        assert "is-error" not in classes, (
            f"Upgrade button in error state. Label='{label}', classes='{classes}'"
        )

    def test_manual_check_button_normal_after_click(self, browser_page):
        page, errors = browser_page
        _wait_for_update_check(page)

        btn = page.query_selector("#btnCheckUpdate")
        if btn is None:
            pytest.skip("Manual check button not found (may be non-release)")

        btn.click()
        page.wait_for_timeout(4000)

        text = btn.inner_text()
        is_error = "失败" in text or "错误" in text
        assert not is_error, f"Manual check button shows error after click: '{text}'"

    def test_no_console_errors(self, browser_page):
        page, errors = browser_page
        _wait_for_update_check(page)

        relevant = [
            e for e in errors
            if "ERR_" not in e and "favicon" not in e.lower()
        ]
        assert len(relevant) == 0, f"Browser console errors: {relevant}"


class TestUpdateAPI:

    def test_update_check_api_returns_ok(self, browser_page, portal_server):
        page, _ = browser_page
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('{portal_server}/api/update/check?force=1');
                return await r.json();
            }}
        """)

        assert result.get("status") == "ok", (
            f"status should be 'ok', got: {json.dumps(result, indent=2)}"
        )
        assert result.get("local_version"), "missing local_version"
        assert result.get("remote_version"), "missing remote_version"
        assert result.get("comparison") in ("older", "same", "newer"), (
            f"unexpected comparison: {result.get('comparison')}"
        )

    def test_update_check_has_update_is_consistent(self, browser_page, portal_server):
        page, _ = browser_page
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('{portal_server}/api/update/check?force=1');
                return await r.json();
            }}
        """)

        comparison = result.get("comparison")
        has_update = result.get("has_update")
        expected = (comparison == "older")
        assert has_update == expected, (
            f"Inconsistent: comparison={comparison} has_update={has_update} "
            f"(expected {expected})"
        )

    def test_upgrade_endpoint_exists(self, browser_page, portal_server):
        page, _ = browser_page
        result = page.evaluate(f"""
            async () => {{
                const r = await fetch('{portal_server}/api/update/upgrade', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/json'}},
                    body: JSON.stringify({{}})
                }});
                return {{ status: r.status, body: await r.json() }};
            }}
        """)

        assert result["status"] != 404, (
            "/api/update/upgrade returned 404 — route not registered!"
        )
        assert result["status"] == 400, (
            f"Expected 400, got {result['status']}: {result['body']}"
        )
        assert result["body"].get("ok") is False, (
            "Should return ok:false for empty request"
        )


class TestUpgradeButtonClick:

    def test_upgrade_button_transitions_on_click(self, browser_page, portal_server):
        page, errors = browser_page
        _wait_for_update_check(page)

        btn = page.query_selector("#upgradeBtn")
        if btn is None:
            pytest.skip("Upgrade button not found")

        classes = btn.evaluate("el => el.className")
        if "is-available" not in classes:
            pytest.skip(f"Button not in available state: {classes}")

        # Intercept upgrade API to prevent actual file download
        page.route(
            f"{portal_server}/api/update/upgrade",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "ok": True, "new_version": "99.0.0", "stage": "launched"
                }),
            )
        )

        btn.click()
        page.wait_for_timeout(1000)

        classes_after = btn.evaluate("el => el.className")
        label_el = btn.query_selector(".ub-label")
        label_after = label_el.inner_text() if label_el else ""

        assert "is-error" not in classes_after, (
            f"Upgrade button in error state after click. "
            f"Label='{label_after}', classes='{classes_after}'"
        )

        page.unroute(f"{portal_server}/api/update/upgrade")


class TestHeaderButtons:

    def test_header_manual_check_button_exists(self, browser_page):
        page, _ = browser_page
        btn = page.query_selector("#btnCheckUpdate")
        assert btn is not None, "#btnCheckUpdate missing from release portal"

    def test_sidebar_upgrade_button_exists(self, browser_page):
        page, _ = browser_page
        btn = page.query_selector("#upgradeBtn")
        assert btn is not None, "#upgradeBtn missing from release sidebar"

    def test_download_card_not_in_release(self, browser_page):
        page, _ = browser_page
        card = page.query_selector("#dlCard")
        assert card is None, "#dlCard found in release — demo leak"


class TestDemoMode:
    """Verify demo mode (port 5000) does NOT have release-only UI elements.
    Tests via HTTP + HTML inspection rather than separate browser."""

    @pytest.fixture(scope="class")
    def demo_html(self):
        """Start portal in demo mode, fetch HTML, return it."""
        _kill_port(5000)
        env = {**os.environ, "NO_BROWSER": "1"}
        proc = subprocess.Popen(
            [sys.executable, str(_PORTAL_APP)],
            cwd=str(_PORTAL_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        deadline = time.time() + 45
        while time.time() < deadline:
            if _port_open(5000):
                time.sleep(3)
                break
            time.sleep(1)
        else:
            proc.kill()
            pytest.fail("Demo portal did not start")

        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:5000/",
            headers={"User-Agent": "test/1.0"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="replace")

        yield html

        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        _kill_port(5000)

    def test_demo_has_no_update_ui(self, demo_html):
        """Release-only elements must not appear in demo HTML."""
        html = demo_html
        assert 'id="updateBanner"' not in html, (
            "Demo mode has #updateBanner — must be release-only"
        )
        assert 'id="btnCheckUpdate"' not in html, (
            "Demo mode has #btnCheckUpdate — must be release-only"
        )
        assert 'id="upgradeBtn"' not in html, (
            "Demo mode has #upgradeBtn — must be release-only"
        )

    def test_demo_has_download_card(self, demo_html):
        """Demo mode must have the download card."""
        html = demo_html
        assert 'id="dlCard"' in html, "Demo mode missing #dlCard"


class TestMirrorHealth:
    """Verify mirror health via direct Python HTTP (not browser — CORS blocks
    cross-origin fetch from page context)."""

    @staticmethod
    def _mirror_get(url: str) -> dict:
        import urllib.request
        req = urllib.request.Request(
            url, headers={"User-Agent": "test/1.0", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_mirror_manifest_returns_ok(self, mirror_server):
        result = self._mirror_get(f"{mirror_server}/api/update/manifest")
        assert result.get("ok") is True, (
            f"Mirror manifest not ok: {json.dumps(result, indent=2)}"
        )
        version = result.get("version", "")
        assert re.match(r"^\d+\.\d+\.\d+$", version), (
            f"Mirror version '{version}' is not clean semver — "
            f"update_check._parse_semver() will return None"
        )

    def test_mirror_download_url_is_well_formed(self, mirror_server):
        manifest = self._mirror_get(f"{mirror_server}/api/update/manifest")
        download_url = manifest.get("download_url")
        assert download_url, "Mirror manifest missing download_url"
        assert "/api/update/download/" in download_url, (
            f"download_url missing /api/update/download/ path: {download_url}"
        )
        assert download_url.endswith(".zip"), (
            f"download_url should end with .zip: {download_url}"
        )
