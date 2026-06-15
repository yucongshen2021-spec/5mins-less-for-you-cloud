"""portal 烟雾测试 — release 模式 (RELEASE_MODE=1, port 5000)。

验证 RELEASE_MODE 下的功能：更新检查 / 页面特征 / 代理。
注意：在线升级(/api/update/upgrade)和重启(/api/shutdown)仅在 release 分支存在，
      main 分支的 RELEASE_MODE 只影响页面显示文字。
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

PORTAL_DIR = APPLICATION_DIR / "portal"
APP = PORTAL_DIR / "app.py"
PORT = 7000  # RELEASE_MODE=1 时 portal 启动在 7000
SUB_PORTS = (7001, 7002, 7003, 7004)


def _post_json(url: str, data: dict, timeout: float = 10.0) -> tuple[int, dict]:
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json", "User-Agent": "test/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


@pytest.fixture(scope="module")
def release_portal():
    """启动 release 版 portal (RELEASE_MODE=1, port 7000)。"""
    if not APP.is_file():
        pytest.skip(f"未找到 {APP}")
    with SmokeServer(
        [PYTHON, str(APP)],
        cwd=PORTAL_DIR,
        port=PORT,
        extra_env={"RELEASE_MODE": "1"},
    ):
        yield f"http://127.0.0.1:{PORT}"


# ── 基础 ──

def test_index_returns_200(release_portal):
    status, body = http_get(release_portal + "/")
    assert status == 200, f"release portal / 应返回 200, 实际 {status}"
    assert body.strip(), "release portal / 返回空响应"


def test_status_api_lists_4_apps(release_portal):
    status, body = http_get(release_portal + "/api/status", timeout=15.0)
    assert status == 200
    apps = json.loads(body)
    ids = {a["id"] for a in apps}
    assert ids == {"all_in_one", "test_report", "domain_capture", "config_analyzer"}


# ── 更新检查 ──

def test_update_check_returns_json(release_portal):
    """release 版必须有 /api/update/check 并返回合法 JSON。"""
    status, body = http_get(release_portal + "/api/update/check", timeout=10.0)
    assert status == 200, f"/api/update/check 应 200, 实际 {status}"
    data = json.loads(body)
    assert "status" in data, f"缺少 status 字段: {data}"
    # status 应为 "ok" / "network_error" / "config_error" 之一
    assert data["status"] in ("ok", "network_error", "config_error"), \
        f"status 值异常: {data['status']}"


def test_update_check_force_refresh(release_portal):
    """force=1 跳过缓存强制刷新。"""
    status, body = http_get(release_portal + "/api/update/check?force=1", timeout=10.0)
    assert status == 200
    data = json.loads(body)
    assert "status" in data


def test_update_check_response_has_local_version(release_portal):
    """返回数据包含 local_version。"""
    _, body = http_get(release_portal + "/api/update/check", timeout=10.0)
    data = json.loads(body)
    assert "local_version" in data, f"缺少 local_version: {data}"


# ── 升级 & 重启（release 分支专属，main 分支应 404）──

def test_upgrade_endpoint_not_in_main(release_portal):
    """RELEASE_MODE=1 时升级端点存在，但缺少 download_url 应返回 400。"""
    body = json.dumps({}).encode("utf-8")
    req = urllib.request.Request(
        release_portal + "/api/update/upgrade",
        data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10.0)
        pytest.fail("缺少 download_url 应返回错误")
    except urllib.error.HTTPError as e:
        assert e.code == 400, f"应 400, 实际 {e.code}"


def test_shutdown_route_present_in_release(release_portal):
    """release 运行时(RELEASE_MODE=1)必须有 /api/shutdown（升级后重启用）。

    历史背景：旧测试 test_shutdown_not_in_main 既想测 demo 不暴露此端点、
    又用了 release_portal fixture，自相矛盾。正确的不变量分两半：
      - release 运行时：路由存在 → 200 ok  （本测试，通过子进程验证，
        不真打 HTTP，避免 os.kill 杀掉 fixture 服务进程）
      - demo 运行时：路由 404  （由 test_demo_runtime_has_no_shutdown 验证）
    """
    import subprocess
    # 用独立子进程设 RELEASE_MODE=1 后跑 test_client，避免污染当前进程
    code = (
        "import os, sys; sys.path.insert(0, r'" + str(PORTAL_DIR) + "'); "
        "os.environ['RELEASE_MODE']='1'; "
        "import app as m; "
        "r = m.app.test_client().post('/api/shutdown'); "
        "print('STATUS', r.status_code); "
        "assert r.status_code==200, r.status_code; "
        "assert r.get_json()=={'ok': True}"
    )
    out = subprocess.run(
        [PYTHON, "-c", code], capture_output=True, text=True, encoding="utf-8",
        timeout=30,
    )
    assert out.returncode == 0, f"release shutdown 测试失败:\n{out.stdout}\n{out.stderr}"
    assert "STATUS 200" in out.stdout


def test_demo_runtime_has_no_shutdown():
    """demo 运行时(RELEASE_MODE 未设置) /api/shutdown 必须返回 404。

    防止 demo 客户被诱导自我关闭（demo 没有升级流程，见 app.py 注释）。
    """
    import subprocess
    code = (
        "import os, sys; "
        "os.environ.pop('RELEASE_MODE', None); "
        "sys.path.insert(0, r'" + str(PORTAL_DIR) + "'); "
        "import app as m; "
        "r = m.app.test_client().post('/api/shutdown'); "
        "print('STATUS', r.status_code); "
        "assert r.status_code==404, r.status_code"
    )
    out = subprocess.run(
        [PYTHON, "-c", code], capture_output=True, text=True, encoding="utf-8",
        timeout=30,
        # 显式清掉 RELEASE_MODE，防止当前 pytest 进程环境泄漏到子进程
        env={k: v for k, v in __import__("os").environ.items() if k != "RELEASE_MODE"},
    )
    assert out.returncode == 0, f"demo shutdown 测试失败:\n{out.stdout}\n{out.stderr}"
    assert "STATUS 404" in out.stdout


# ── 代理 ──

def test_proxy_config_analyzer_reachable(release_portal):
    """通过 release portal 代理访问各子应用。"""
    status, body = http_get(release_portal + "/app/config_analyzer/", timeout=10.0)
    assert status == 200, f"config_analyzer 代理应 200, 实际 {status}"
    assert "configText" in body or "ER/USG" in body, \
        "config_analyzer 代理返回内容异常"


def test_proxy_all_in_one_reachable(release_portal):
    status, _ = http_get(release_portal + "/app/all_in_one/api/scenarios", timeout=10.0)
    assert status == 200, f"all_in_one 代理应 200, 实际 {status}"


# ── 发布版页面特征 ──

def test_page_shows_release_badge(release_portal):
    """RELEASE_MODE=1 页面应显示「正式版」。"""
    _, body = http_get(release_portal + "/")
    assert "正式版" in body, "RELEASE_MODE=1 页面应含「正式版」"


def test_page_has_download_card(release_portal):
    """左下角应有下载卡片 dlCard（main 分支模板）。"""
    _, body = http_get(release_portal + "/")
    # main 分支: 下载完整应用 dlCard；release 分支: upgradeBtn
    has_dl = 'id="dlCard"' in body
    has_upgrade = 'id="upgradeBtn"' in body
    assert has_dl or has_upgrade, "页面应有 dlCard 或 upgradeBtn"


def test_page_has_update_banner(release_portal):
    """应有 updateBanner 元素（默认隐藏）。"""
    _, body = http_get(release_portal + "/")
    assert 'id="updateBanner"' in body, "release 版应有 updateBanner"
