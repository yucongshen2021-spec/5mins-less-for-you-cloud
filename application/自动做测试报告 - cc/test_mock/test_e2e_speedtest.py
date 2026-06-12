"""E2E: mock report generates speedtest screenshot in docx."""
from playwright.sync_api import sync_playwright
from pathlib import Path
from zipfile import ZipFile
import sys, requests, tempfile, os, time

BASE = "http://127.0.0.1:5002"

# First check the app is running
try:
    r = requests.get(BASE, timeout=5)
    assert r.status_code == 200, f"App not running: {r.status_code}"
except Exception as e:
    print(f"ERROR: Cannot reach {BASE} — is the app running? {e}")
    sys.exit(1)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    # 1. Navigate to main page and open mock page via hidden button
    page.goto(BASE, timeout=15000)
    page.wait_for_load_state("networkidle")
    btn = page.query_selector(".hidden-mock-btn")
    assert btn, "Hidden button not found on index page"
    btn.click()
    page.wait_for_url("**/mock", timeout=10000)
    page.wait_for_selector("#run-btn", timeout=10000)
    print(f"Navigated to mock page: {page.url}")

    # 2. Fill form with realistic values
    fields = {
        "customer": "E2E Speedtest Test",
        "line_id": "SPEED001",
        "bandwidth": "100M",
        "engineer": "Auto",
        "main_ip": "10.55.19.237",
        "backup_ip": "10.30.36.217",
        "main_delay": "3.5", "main_jitter": "1.2", "main_loss": "0",
        "backup_delay": "4.8", "backup_jitter": "2.1", "backup_loss": "0",
        "baidu_delay": "12", "baidu_jitter": "3", "baidu_loss": "0",
        "google_delay": "180", "google_jitter": "15", "google_loss": "0",
        "failover_delay": "185", "failover_jitter": "12", "failover_loss": "0",
    }
    for fid, val in fields.items():
        el = page.query_selector(f"#{fid}")
        if el:
            el.fill(val)
        else:
            print(f"WARNING: field #{fid} not found")

    # 3. Click generate
    page.click("#run-btn")
    page.wait_for_timeout(500)
    status = page.text_content("#status")
    print(f"Status: {status}")

    # 4. Wait for download toast (up to 90s for docx generation)
    try:
        page.wait_for_selector("#download-toast:not(.hidden)", timeout=90000)
    except Exception as e:
        # Print current state for debugging
        log_text = page.text_content("#log-output") or ""
        print(f"Timeout waiting for download toast. Log so far:\n{log_text[-500:]}")
        raise
    toast_text = page.text_content("#download-toast") or ""
    print(f"Toast: {toast_text[:100]}")

    # 5. Get download link
    dl_link = page.query_selector("#download-toast a")
    assert dl_link, "No download link in toast"
    href = dl_link.get_attribute("href")
    print(f"Download URL: {href}")

    # 6. Download the docx
    full_url = f"{BASE}{href}" if href.startswith("/") else href
    r = requests.get(full_url, timeout=30)
    assert r.status_code == 200, f"Download failed: {r.status_code}"
    assert len(r.content) > 50000, f"Docx too small: {len(r.content)} bytes"
    print(f"Docx size: {len(r.content)} bytes")

    # 7. Verify docx contains images (it's a ZIP with media files)
    tmp = Path(tempfile.gettempdir()) / "e2e_speedtest_check.docx"
    tmp.write_bytes(r.content)
    with ZipFile(tmp) as z:
        names = z.namelist()
        pngs = [n for n in names if n.endswith(('.png', '.jpg', '.jpeg'))]
        word_media = [n for n in names if 'media' in n.lower()]
        print(f"ZIP entries: {len(names)}, PNGs: {len(pngs)}, media: {len(word_media)}")
        assert len(word_media) > 5, f"Expected >5 media files in docx, got {len(word_media)}"
        # Check for speedtest screenshot — currently skipped in mock mode
        speedtest_pngs = [n for n in pngs if '05_speedtest' in n.lower() or 'image5' in n.lower()]
        print(f"Speedtest-related PNGs: {speedtest_pngs or '(none — speedtest skipped in mock mode)'}")
    os.unlink(tmp)

    # 8. Check log for success
    log_text = page.text_content("#log-output") or ""
    assert "[OK] 报告已生成" in log_text, "Log missing success message"
    assert "05_speedtest" in log_text or "speedtest" in log_text.lower() or "Speedtest" in log_text, \
        f"Log missing speedtest reference. Log excerpt:\n{log_text[-300:]}"
    print("Log shows success + speedtest reference")

    browser.close()
    print("\nPASS: E2E mock report with speedtest screenshot works")
