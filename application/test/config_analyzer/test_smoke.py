"""自动梳理配置 (config_analyzer) 烟雾测试 — Flask 版。

应用本体是 er_config_analyzer.html 纯前端静态页面，
由 app.py (Flask) 托管，与其他子应用一致。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _smoke_helpers import APPLICATION_DIR, PYTHON, SmokeServer, http_get

APP_DIR = APPLICATION_DIR / "自动梳理配置 - cc"
APP = APP_DIR / "app.py"
HTML = APP_DIR / "er_config_analyzer.html"
PORT = 5004


@pytest.fixture(scope="module")
def server():
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    if not HTML.is_file():
        pytest.skip(f"未找到 {HTML}")
    with SmokeServer([PYTHON, str(APP)], cwd=APP_DIR, port=PORT):
        yield f"http://127.0.0.1:{PORT}"


# ── 基础 HTML 加载 ──

def test_html_returns_200(server):
    status, body = http_get(server + "/", timeout=10.0)
    assert status == 200, f"config_analyzer / 应返回 200, 实际 {status}"
    assert body.strip(), "首页应返回非空内容"


def test_page_has_config_textarea(server):
    """核心 textarea #configText 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="configText"' in body, "页面缺少核心 textarea configText"


def test_page_has_analyze_button(server):
    """解析按钮 #btnAnalyze 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="btnAnalyze"' in body, "页面缺少解析按钮 btnAnalyze"


def test_page_has_mapping_textarea(server):
    """IP 映射 textarea #mappingText 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="mappingText"' in body, "页面缺少映射 textarea mappingText"


def test_page_has_export_button(server):
    """导出按钮 #btnExport 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="btnExport"' in body, "页面缺少导出按钮 btnExport"


def test_page_has_clear_button(server):
    """清空按钮 #btnClear 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="btnClear"' in body, "页面缺少清空按钮 btnClear"


def test_page_has_result_tabs(server):
    """结果标签页 NAT表 / ER Topology 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="tabNat"' in body, "页面缺少 NAT 表 tab"
    assert 'id="tabTopology"' in body, "页面缺少 Topology tab"


def test_page_has_svg_container(server):
    """拓扑 SVG 容器 #topoSvg 必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert 'id="topoSvg"' in body, "页面缺少 SVG 容器 topoSvg"


# ── JavaScript 逻辑存在性 ──

def test_page_has_parse_er_config(server):
    """parseERConfig 函数必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert "parseERConfig" in body, "页面缺少 parseERConfig 函数"


def test_page_has_parse_usg_config(server):
    """parseUSGConfig 函数必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert "parseUSGConfig" in body, "页面缺少 parseUSGConfig 函数"


def test_page_has_parse_mapping(server):
    """parseFakeRealMapping 函数必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert "parseFakeRealMapping" in body, "页面缺少 parseFakeRealMapping 函数"


def test_page_has_draw_topology(server):
    """draw 函数必须存在 (拓扑绘制)。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert "function draw(" in body, "页面缺少 draw 函数"


def test_page_has_render_nat_table(server):
    """renderNATTable 函数必须存在。"""
    _, body = http_get(server + "/", timeout=10.0)
    assert "renderNATTable" in body, "页面缺少 renderNATTable 函数"


# ── 静态文件服务 ──

def test_er_config_analyzer_html_directly_accessible(server):
    """直接路径 /er_config_analyzer.html 也能访问。"""
    status, body = http_get(server + "/er_config_analyzer.html", timeout=10.0)
    assert status == 200, f"直接路径应返回 200, 实际 {status}"
    assert "configText" in body


def test_content_type_is_html(server):
    """响应 Content-Type 为 text/html。"""
    req = urllib.request.Request(
        server + "/",
        headers={"User-Agent": "test/1.0"},
    )
    with urllib.request.urlopen(req, timeout=10.0) as r:
        ct = r.headers.get("Content-Type", "")
        assert "text/html" in ct, f"Content-Type 应为 text/html, 实际 {ct}"
