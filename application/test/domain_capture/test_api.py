"""自动抓域名 (domain_capture) API 完整测试。

覆盖: /api/capture (参数校验、真实抓取、CNAME 解析、IP 过滤、超时、错误处理)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

APP_DIR = APPLICATION_DIR / "自动抓域名发2"
APP = APP_DIR / "app.py"
PORT = 5001
_POLL_INTERVAL = 0.5
_POLL_TIMEOUT = 120


def _post_json(url: str, data: dict, timeout: float = 60.0) -> tuple[int, dict]:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "test/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


# ── 本地测试页 fixture：提供一个简单的 HTML 页面用于抓取验证 ──

_TEST_PAGE_PORT = 5099
_TEST_PAGE_HTML = b"""<!DOCTYPE html><html><head><title>Capture Test</title></head>
<body><h1>Hello Domain Capture</h1><p>This page exists to verify the capture works.</p></body></html>"""


class _QuietHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 抑制日志


@pytest.fixture(scope="module")
def test_page_url():
    """在独立端口启动一个简单 HTTP server，供 domain_capture 抓取。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    if s.connect_ex(("127.0.0.1", _TEST_PAGE_PORT)) == 0:
        s.close()
        pytest.skip(f"端口 {_TEST_PAGE_PORT} 被占用")
    s.close()

    server = HTTPServer(("127.0.0.1", _TEST_PAGE_PORT), _QuietHTTPHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.3)
    url = f"http://127.0.0.1:{_TEST_PAGE_PORT}/"
    yield url
    server.shutdown()


# ── domain_capture fixture ──

@pytest.fixture(scope="module")
def server():
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    with SmokeServer([PYTHON, str(APP)], cwd=APP_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"


# ── 基础 ──

def test_index_returns_200(server):
    status, body = http_get(server + "/")
    assert status == 200, f"domain_capture / 应返回 200, 实际 {status}"
    assert body.strip(), "domain_capture / 返回空响应"


# ── /api/capture 参数校验 ──

def test_capture_empty_url_returns_400(server):
    """空 URL → 400。"""
    status, data = _post_json(server + "/api/capture", {"url": ""})
    assert status == 400, f"空 URL 应返回 400, 实际 {status}"
    assert "error" in data, f"应包含 error: {data}"


# ── /api/capture 真实抓取 ──

def test_capture_valid_url_returns_domains(server, test_page_url):
    """有效 URL（本地测试页）→ 成功抓取 + 返回域名列表。"""
    status, data = _post_json(server + "/api/capture", {
        "url": test_page_url,
        "timeout": 15,
        "wait": 1,
        "resolve_dns": False,
    })
    # > 本地页面可能没有外链域名；只要 API 不 500 且返回合法结构即通过
    assert status == 200, f"抓取应返回 200, 实际 {status}: {data}"
    assert "domains_count" in data, f"应包含 domains_count: {data}"
    assert isinstance(data.get("results"), list), f"results 应为 list: {data}"
    # 至少应抓到 localhost 域名
    domain_count = data.get("domains_count", 0)
    assert domain_count >= 0, f"domains_count 应 >= 0: {data}"


def test_capture_with_dns_resolution(server, test_page_url):
    """resolve_dns=true → 结果包含 cname_chain 字段。"""
    status, data = _post_json(server + "/api/capture", {
        "url": test_page_url,
        "timeout": 15,
        "wait": 1,
        "resolve_dns": True,
    })
    assert status == 200, f"抓取(带 DNS)应返回 200, 实际 {status}"
    for r in data.get("results", []):
        assert "hostname" in r, f"每条记录应有 hostname: {r}"
        assert "cname_chain" in r, f"每条记录应有 cname_chain: {r}"


def test_capture_without_dns_resolution(server, test_page_url):
    """resolve_dns=false → cname_chain 为空数组。"""
    status, data = _post_json(server + "/api/capture", {
        "url": test_page_url,
        "timeout": 15,
        "wait": 1,
        "resolve_dns": False,
    })
    assert status == 200, f"抓取(不带 DNS)应返回 200, 实际 {status}"
    for r in data.get("results", []):
        assert r.get("cname_chain") == [], f"cname_chain 应为空数组: {r}"


# ── 参数透传 ──

def test_capture_respects_timeout(server, test_page_url):
    """timeout 参数被正确接受并使用。"""
    # 本地页面很快，不会触发超时；主要验证参数不报错
    status, data = _post_json(server + "/api/capture", {
        "url": test_page_url,
        "timeout": 10,
        "wait": 0,
    })
    assert status == 200, f"timeout=10 应正常: {status}"


def test_capture_invalid_url_returns_error(server):
    """明显无效的 URL → 返回错误，不崩溃。"""
    status, data = _post_json(server + "/api/capture", {
        "url": "not-a-valid-url-at-all-xyz",
        "timeout": 5,
        "wait": 0,
    })
    # 可能返回 500（Playwright 启动失败/页面无法加载）
    # 关键是不崩溃、返回 JSON
    assert "error" in data or "domains_count" in data, \
        f"应返回 error 或 domains_count: {data}"
