"""portal 烟雾测试 (demo 版, port 5000-5004)。"""
from __future__ import annotations

import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import psutil  # 没装也没关系 — fallback 用 PowerShell 兜底
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

PORTAL_DIR = APPLICATION_DIR / "portal"
APP = PORTAL_DIR / "app.py"
PORT = 5000
SUB_PORTS = (5001, 5002, 5003, 5004)


def _kill_listeners(ports: tuple[int, ...]) -> None:
    """杀掉监听给定端口的进程（Windows / cross-platform via psutil）。"""
    for p in psutil.process_iter(["pid", "name"]):
        try:
            for c in p.net_connections(kind="inet"):
                if c.laddr and c.laddr.port in ports and c.status in ("LISTEN", "ESTABLISHED"):
                    p.kill()
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.3)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@pytest.fixture(scope="module")
def portal_running():
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    with SmokeServer([PYTHON, str(APP)], cwd=PORTAL_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"
    # SmokeServer 已 terminate portal；下面清理 portal 拉起来的子进程
    _kill_listeners(SUB_PORTS + (PORT,))


def test_index_returns_200(portal_running):
    status, body = http_get(portal_running + "/")
    assert status == 200, f"portal / 应返回 200, 实际 {status}"
    assert body.strip(), "portal / 返回空响应"


def test_status_api_lists_sub_apps(portal_running):
    status, body = http_get(portal_running + "/api/status", timeout=10.0)
    assert status == 200, f"portal /api/status 应返回 200, 实际 {status}"
    apps = json.loads(body)
    assert isinstance(apps, list) and apps, f"/api/status 返回不是应用列表: {apps!r}"
    ids = {a["id"] for a in apps if isinstance(a, dict) and "id" in a}
    expect = {"all_in_one", "test_report", "domain_capture", "config_analyzer"}
    missing = expect - ids
    assert not missing, f"portal /api/status 缺少子应用: {missing} (got {ids})"


def test_download_latest_returns_json(portal_running):
    """无论有无 dist zip，端点都应返回合法 JSON 且不 500。"""
    status, body = http_get(portal_running + "/api/download/latest", timeout=10.0)
    assert status == 200, f"/api/download/latest 应返回 200, 实际 {status}"
    data = json.loads(body)
    assert "available" in data, f"缺少 available: {data}"
    if data["available"]:
        assert "version" in data
        assert "filename" in data
        assert isinstance(data.get("size_mb"), (int, float))


def test_proxy_passes_api_through(portal_running):
    """通过代理访问 all_in_one 子应用 API，返回 200。"""
    status, body = http_get(portal_running + "/app/all_in_one/api/scenarios", timeout=10.0)
    assert status == 200, f"代理 scenarios 应返回 200, 实际 {status}"
    data = json.loads(body)
    assert isinstance(data, dict) and "scenarios" in data, \
        f"scenarios 应返回含 scenarios 字段的 dict, 实际 {type(data)}"


def test_proxy_handles_chinese_url_path(portal_running):
    """含中文和特殊字符的路径经代理后不应返回 502（此前有 bug）。"""
    raw_path = "/app/all_in_one/api/notes/epoch_fastip?variant=hk"
    status, _ = http_get(portal_running + raw_path, timeout=10.0)
    assert status == 200, f"代理中文路径应返回 200, 实际 {status}"


# ── Demo 版功能开关测试 ──

def test_demo_download_endpoint_exists(portal_running):
    """Demo 版必须保留 /api/download/latest。"""
    status, body = http_get(portal_running + "/api/download/latest", timeout=10.0)
    assert status == 200, f"demo 版 /api/download/latest 应 200, 实际 {status}"
    data = json.loads(body)
    assert "available" in data


def test_demo_update_check_not_found(portal_running):
    """Demo 版不应暴露 /api/update/check（不导入 update_check）。"""
    try:
        http_get(portal_running + "/api/update/check", timeout=10.0)
        assert False, "demo 版不应有 /api/update/check"
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"应 404, 实际 {e.code}"


def test_demo_update_upgrade_not_found(portal_running):
    """Demo 版不应暴露 /api/update/upgrade（不导入 upgrade）。"""
    data = json.dumps({"download_url": "http://x"}).encode("utf-8")
    req = urllib.request.Request(
        portal_running + "/api/update/upgrade",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10.0)
        assert False, "demo 版不应有 /api/update/upgrade"
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"应 404, 实际 {e.code}"
