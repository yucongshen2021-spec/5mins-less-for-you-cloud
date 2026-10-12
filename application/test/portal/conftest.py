"""portal 测试 —— 8000 测试容器未就绪时整组自动跳过（与 test_smoke 内守卫一致）。

本地：需先起测试容器（sudo docker-compose -f docker-compose.test.yml up -d）；
CI：无容器 → 本目录全部用例自动跳过，不阻塞 workflow。
"""
from __future__ import annotations

import socket
import time
import urllib.request

import pytest

BASE = "http://127.0.0.1:8000"


def _port_open(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


@pytest.fixture(scope="session", autouse=True)
def _require_live_8000():
    if not _port_open(8000):
        pytest.skip("8000 测试容器未运行；启动: sudo docker-compose -f docker-compose.test.yml up -d")
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"{BASE}/api/health", timeout=3) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(1)
    pytest.skip("8000 容器 /api/health 30s 内未就绪")
