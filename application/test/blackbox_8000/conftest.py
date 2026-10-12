"""blackbox_8000 —— 目标服务未就绪时整组自动跳过。

本地：需要 8000 测试容器在跑（sudo docker-compose -f docker-compose.test.yml up -d）；
CI：无容器运行 → 所有 blackbox 用例自动跳过，不阻塞 workflow。
"""
from __future__ import annotations

import os
import urllib.request

import pytest

BASE = os.environ.get("BLACKBOX_BASE", "http://127.0.0.1:8000").rstrip("/")


def _service_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{BASE}/api/health", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _require_live_8000():
    if not _service_ready():
        pytest.skip(f"8000 容器未就绪（{BASE}/api/health 不可达），跳过 blackbox_8000 全部用例")
    return True
