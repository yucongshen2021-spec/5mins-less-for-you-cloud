"""portal 烟雾测试 — 针对 8000 测试容器（docker-compose.test.yml）。

历史上此文件自启 portal(5000) 并期望 4 个子应用 + /api/download/latest +
/api/update/check 路由。Demo 版收敛后这些已不成立：
  - 仅 all_in_one 可见（test_report/config_analyzer/domain_capture 被隐藏）
  - /api/download/latest、/api/update/check 路由已移除
故改为打 8000 测试容器做基础烟雾，全量 API 由 test/blackbox_8000/ 覆盖。

前置：8000 容器在跑（sudo /usr/local/bin/docker-compose -f
docker-compose.test.yml up -d）。
"""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.request

import pytest

BASE = os.environ.get("BLACKBOX_BASE", "http://127.0.0.1:8000").rstrip("/")


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def _get(path: str, timeout: float = 10.0):
    req = urllib.request.Request(BASE + path, headers={"User-Agent": "smoke/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


@pytest.fixture(scope="module", autouse=True)
def container_up():
    """8000 容器必须在跑，否则整体跳过（而非假成功）。"""
    if not _port_open(8000):
        pytest.skip("8000 测试容器未运行；启动: sudo docker-compose -f "
                    "docker-compose.test.yml up -d")
    # 容器起来了不代表 portal 就绪，等 /api/health
    for _ in range(30):
        try:
            st, _ = _get("/api/health", timeout=3)
            if st == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    pytest.skip("8000 容器 /api/health 30s 内未就绪")


def test_index_returns_200():
    status, body = _get("/")
    assert status == 200, f"portal / 应返回 200, 实际 {status}"
    assert body.strip(), "portal / 返回空响应"


def test_health_ok():
    status, body = _get("/api/health")
    assert status == 200
    data = json.loads(body)
    assert data.get("ok") is True


def test_status_lists_all_in_one():
    """Demo 版仅 all_in_one 可见（其余 3 个被 _HIDDEN_IDS 隐藏，非误删）。"""
    status, body = _get("/api/status")
    assert status == 200
    apps = json.loads(body)
    assert isinstance(apps, list) and apps, f"/api/status 返回不是应用列表: {apps!r}"
    ids = {a["id"] for a in apps if isinstance(a, dict) and "id" in a}
    assert "all_in_one" in ids, f"缺少 all_in_one: {ids}"
    aio = next(a for a in apps if a["id"] == "all_in_one")
    assert aio.get("reachable"), f"all_in_one 不可达: {aio}"


def test_proxy_passes_api_through():
    """通过反代访问 all_in_one 子应用 API，返回 200。"""
    status, body = _get("/app/all_in_one/api/scenarios", timeout=10.0)
    assert status == 200, f"代理 scenarios 应返回 200, 实际 {status}"
    data = json.loads(body)
    assert isinstance(data, dict) and "scenarios" in data, \
        f"scenarios 应返回含 scenarios 字段的 dict, 实际 {type(data)}"


def test_proxy_passes_notes_through():
    """含中文 query 的路径经代理后不应 502（此前有 bug）。"""
    status, _ = _get("/app/all_in_one/api/notes/epoch_fastip?variant=hk", timeout=10.0)
    assert status == 200, f"代理 notes 应返回 200, 实际 {status}"
