"""自动梳理配置 (config_analyzer) 烟雾测试。

应用本体是 HTML 静态文件，运行时由 `py -3 -m http.server` 托管。
这里只验证静态文件能被 HTTP 200 取出，并包含核心 textarea id `configText`。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

APP_DIR = APPLICATION_DIR / "自动梳理配置 - cc"
HTML = APP_DIR / "er_config_analyzer.html"
PORT = 5742


@pytest.fixture(scope="module")
def server():
    if not HTML.is_file():
        pytest.skip(f"未找到 {HTML}")
    args = [PYTHON, "-m", "http.server", str(PORT), "--bind", "127.0.0.1"]
    with SmokeServer(args, cwd=APP_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"


def test_html_returns_200(server):
    status, body = http_get(server + "/er_config_analyzer.html", timeout=10.0)
    assert status == 200, f"er_config_analyzer.html 应返回 200, 实际 {status}"
    assert 'id="configText"' in body, "页面缺少核心 textarea configText，应用入口异常"
    assert "parseERConfig" in body, "页面缺少 parseERConfig 函数，JS 逻辑可能损坏"
