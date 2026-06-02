"""端到端更新流程测试 — 模拟客户真实环境。

流程:
  1. 从 dist/ 解压旧版本 zip → 临时目录
  2. 用包内 Python 启动 portal
  3. 验证: 端口 7000, API 检测到更新, 页面显示横幅

前置条件:
  - dist/ 必须有至少 2 个版本 zip (如 v1.0.5 和 v1.0.6)
  - mirror 服务已启动: py tools/serve_mirror.py --port 8000
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DIST_DIR = PROJECT_ROOT / "dist"
BUNDLE_NAME = "帮你节省5分钟"
TEMP_ROOT = PROJECT_ROOT / ".test_update_tmp"
PORTAL_PORT = 7000
MIRROR_PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORTAL_PORT}"


def _http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "test/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def _port_open(port: int) -> bool:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


# ── helpers ──

def _find_oldest_zip() -> Path | None:
    """返回 dist/ 中最旧的 zip（用于模拟旧版本客户端）。"""
    zips = sorted(DIST_DIR.glob(f"{BUNDLE_NAME}-*.zip"), key=lambda p: p.stat().st_mtime)
    # 至少需要 2 个版本：旧的作为客户端，新的作为"更新目标"
    if len(zips) < 2:
        return None
    return zips[0]  # oldest


def _find_newest_version() -> str:
    zips = sorted(DIST_DIR.glob(f"{BUNDLE_NAME}-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return "?"
    name = zips[0].name
    return name.removeprefix(f"{BUNDLE_NAME}-").removesuffix(".zip")


@pytest.fixture(scope="module")
def client_from_zip():
    """解压最旧版本 zip → 临时目录 → 启动 → yield URL → 清理。"""
    old_zip = _find_oldest_zip()
    if old_zip is None:
        pytest.skip(f"dist/ 中至少需要 2 个版本 zip，当前不足")

    client_ver = old_zip.name.removeprefix(f"{BUNDLE_NAME}-").removesuffix(".zip")
    extract_dir = TEMP_ROOT / f"client_{client_ver}"

    # 清理旧临时目录
    import shutil
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True)

    # 解压
    with zipfile.ZipFile(old_zip) as zf:
        zf.extractall(extract_dir)

    bundle_dir = extract_dir / BUNDLE_NAME
    assert bundle_dir.is_dir(), f"解压后缺少 {BUNDLE_NAME}/"

    python_exe = bundle_dir / "runtime" / "python" / "python.exe"
    assert python_exe.is_file(), f"未找到 {python_exe}"

    app_py = bundle_dir / "application" / "portal" / "app.py"
    assert app_py.is_file(), f"未找到 {app_py}"

    # 启动客户端
    import subprocess, os
    env = {**os.environ, "RELEASE_MODE": "1", "PYTHONNOUSERSITE": "1", "NO_BROWSER": "1"}
    proc = subprocess.Popen(
        [str(python_exe), str(app_py)],
        cwd=str(bundle_dir / "application" / "portal"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    # 等待端口
    deadline = time.time() + 30
    while time.time() < deadline:
        if _port_open(PORTAL_PORT):
            time.sleep(3)  # 给子应用一点启动时间
            break
        time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError(f"客户端 {client_ver} 启动超时")

    yield BASE_URL, client_ver

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

    # 清理临时目录
    shutil.rmtree(extract_dir, ignore_errors=True)


# ── 基础验证 ──

def test_portal_on_7000(client_from_zip):
    """客户端启动后必须在 7000 端口（release）。"""
    base_url, _ = client_from_zip
    status, body = _http_get(base_url + "/")
    assert status == 200, f"portal 应 200, 实际 {status}"
    assert "帮你节省5分钟" in body, "首页应含品牌名"


def test_portal_shows_release_badge(client_from_zip):
    """Release 版显示 RELEASE 标签。"""
    base_url, _ = client_from_zip
    _, body = _http_get(base_url + "/")
    assert "正式版" in body or "RELEASE" in body, "release 版应显示正式版标签"


def test_5000_port_not_open(client_from_zip):
    """demo 端口 5000 不应被 release 客户端占用。"""
    assert not _port_open(5000), "release 客户端不应占用 demo 端口 5000"


# ── 更新检测 ──

def test_update_check_returns_ok(client_from_zip):
    """/api/update/check 返回 status=ok, has_update=True。"""
    base_url, client_ver = client_from_zip
    status, body = _http_get(base_url + "/api/update/check?force=1", timeout=15.0)
    assert status == 200, f"update check 应 200, 实际 {status}"
    data = json.loads(body)

    assert data.get("status") == "ok", f"status 应为 ok: {data}"
    assert data.get("has_update") is True, f"应检测到更新: {data}"
    assert data.get("comparison") == "older", f"客户端应更旧: {data}"
    local = data.get("local_version")
    remote = data.get("remote_version")
    assert local is not None and remote is not None, \
        f"local_version 和 remote_version 不能为 None: {data}"
    # 客户端版本应 < 远端版本
    assert local != remote, f"local 和 remote 不应相同: {local}"
    newest = _find_newest_version()
    assert remote == newest, \
        f"remote_version 应为 {newest}: {data}"
    assert isinstance(data.get("download_url"), str) and data["download_url"], \
        "应包含 download_url"


def test_update_check_no_errors(client_from_zip):
    """更新检查不应有 errors。"""
    base_url, _ = client_from_zip
    _, body = _http_get(base_url + "/api/update/check?force=1", timeout=15.0)
    data = json.loads(body)
    errors = data.get("errors") or []
    assert len(errors) == 0, f"不应有 errors: {errors}"


# ── update_config.json 配置 ──

def test_update_config_has_mirror_url(client_from_zip):
    """解压后的 update_config.json 包含 mirror_url（构建时写入）。"""
    base_url, client_ver = client_from_zip
    extract_dir = TEMP_ROOT / f"client_{client_ver}" / BUNDLE_NAME
    cfg_path = extract_dir / "application" / "portal" / "update_config.json"
    if not cfg_path.is_file():
        pytest.skip("update_config.json 不存在")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    mirror = cfg.get("mirror_url", "").strip()
    mirror_list = cfg.get("mirror_urls") or []
    assert mirror or mirror_list, f"mirror_url 和 mirror_urls 都为空: {cfg}"
