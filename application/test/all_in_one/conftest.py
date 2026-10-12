"""pytest 配置 — 让 Playwright E2E 在 pytest 模式下也可用。

向后兼容独立脚本入口（`python test_e2e_playwright.py`），同时为 pytest 提供：
  - session 级 Flask server fixture（自动启动 / 停止）
  - 函数级 `page` 修饰：每个用例自动 goto BASE

非 e2e 测试不会被影响（fixture 仅在收到 `page` 请求时联动启动 server）。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

import _bootstrap  # noqa: F401 — 同步注入 sys.path/TEST_MODE
from _bootstrap import APP_DIR

PORT = 5003
BASE = f"http://127.0.0.1:{PORT}"
APP_FILE = APP_DIR / "web" / "app.py"
PYTHON = sys.executable


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@pytest.fixture(scope="session")
def flask_server():
    """启动 all_in_one Flask；若端口已被占用就复用。"""
    own_proc = None
    if not _port_in_use(PORT):
        own_proc = subprocess.Popen(
            [PYTHON, str(APP_FILE)],
            cwd=str(APP_DIR / "web"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "TEST_MODE": "1", "NO_BROWSER": "1"},
        )
        for _ in range(90):
            if _port_in_use(PORT):
                time.sleep(2)
                break
            time.sleep(1)
        else:
            own_proc.kill()
            raise RuntimeError("Flask 启动超时")
    yield BASE
    if own_proc is not None:
        own_proc.terminate()
        try:
            own_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            own_proc.kill()


@pytest.fixture
def page(page, flask_server):
    """覆盖 pytest-playwright 默认 page：自动起 server + 跳转首页 + 等加载。"""
    page.set_default_timeout(10000)
    page.goto(flask_server, wait_until="domcontentloaded", timeout=15000)
    page.wait_for_timeout(1000)
    return page


def pytest_collection_modifyitems(config, items):
    """无 pytest-playwright（如 CI / 本机未装）时，自动跳过需要浏览器的用例。

    - 仅影响请求 `page` fixture 或带 `playwright` marker 的用例；
    - 其余测试（in-process test_client 类）不受任何影响。
    """
    try:
        import pytest_playwright  # noqa: F401
        return
    except ImportError:
        pass
    skip = pytest.mark.skip(reason="需要 pytest-playwright + 浏览器（当前环境未安装，自动跳过）")
    for item in items:
        if "page" in item.fixturenames or "playwright" in item.keywords:
            item.add_marker(skip)
