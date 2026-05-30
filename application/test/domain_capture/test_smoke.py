"""自动抓域名发2 (domain_capture) 烟雾测试：起进程 + 首页 200。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

APP_DIR = APPLICATION_DIR / "自动抓域名发2"
APP = APP_DIR / "app.py"
PORT = 5001


@pytest.fixture(scope="module")
def server():
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    with SmokeServer([PYTHON, str(APP)], cwd=APP_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"


def test_index_returns_200(server):
    status, body = http_get(server + "/")
    assert status == 200, f"domain_capture / 应返回 200, 实际 {status}"
    assert body.strip(), "domain_capture / 返回空响应"
