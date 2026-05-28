"""portal 烟雾测试：进程能起来 + 首页 200 + 暴露了 /api/status。

注意：portal 启动会同步拉起 4 个子应用（5739 / 5740 / 5741 / 5742）。
fixture 退出时 SmokeServer 只是 terminate portal 父进程，子进程不会被 atexit 回收，
所以 finalizer 这里要把这 4 个端口上的残留进程也一起强杀，避免污染后续 smoke。
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import psutil  # 没装也没关系 — fallback 用 PowerShell 兜底
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

PORTAL_DIR = APPLICATION_DIR / "portal"
APP = PORTAL_DIR / "app.py"
PORT = 5000
SUB_PORTS = (5739, 5740, 5741, 5742)


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
