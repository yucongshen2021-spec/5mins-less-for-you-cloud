# Demo / Release 双版本分离 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将应用拆分为 demo 版（main 分支，port 5000-5004，有下载无更新）和 release 版（release 分支，port 6000-6004，有更新无下载），两套端口互不冲突。

**Architecture:** 两份独立代码分别在 `main` 和 `release` 分支，目录结构相同但端口和功能开关不同。main 分支永远最新；release 通过 merge main 获得稳定版本。

**Tech Stack:** Python 3.13, Flask, pytest, Playwright

---

## 文件清单

### main 分支（demo 版）修改

| 文件 | 变更 |
|---|---|
| `application/portal/app.py` | 删 update_check/upgrade 导入和端点；删 `/api/shutdown`；保留 download 端点；端口 5000 |
| `application/portal/process_manager.py` | APPS 端口改为 5001-5004 |
| `application/portal/templates/index.html` | 删更新横幅 HTML+CSS+JS、在线升级 JS；保留下载卡片 |
| `application/portal/update_config.json` | mirror_url 置空 |
| `start_all.bat` | 端口改为 5000-5004 |
| `application/test/_smoke_helpers.py` | 不变（路径逻辑通用） |
| `application/test/portal/test_smoke.py` | 端口改为 5000-5004；新增"下载端点存在"测试；新增"更新端点不存在"测试；新增"升级端点不存在"测试 |
| `application/test/config_analyzer/test_smoke.py` | 端口 5742→5004 |
| `application/test/domain_capture/test_smoke.py` | 端口 5739→5001 |
| `application/test/test_report/test_smoke.py` | 端口 5740→5002 |
| `application/test/all_in_one/conftest.py` | 端口 5741→5003 |
| `application/test/all_in_one/test_e2e_playwright.py` | 端口 5741→5003 |
| `.github/workflows/test.yml` | 仅 main 触发；端口 5000-5004；删除 release 相关 job |

### release 分支（交付版）修改

| 文件 | 变更 |
|---|---|
| `application/portal/app.py` | 删 download 端点；保留 update_check/upgrade 导入和端点；端口 6000 |
| `application/portal/process_manager.py` | APPS 端口改为 6001-6004 |
| `application/portal/templates/index.html` | 删下载卡片 HTML+CSS+JS；保留更新横幅和在线升级 |
| `application/portal/update_config.json` | mirror_url 预置（打包时覆盖） |
| `start_all.bat` | 端口改为 6000-6004 |
| `application/test/_smoke_helpers.py` | 不变 |
| `application/test/portal/test_smoke.py` | 端口改为 6000-6004；新增"下载端点不存在"测试；新增"更新端点存在"测试 |
| `application/test/config_analyzer/test_smoke.py` | 端口 5742→6004 |
| `application/test/domain_capture/test_smoke.py` | 端口 5739→6001 |
| `application/test/test_report/test_smoke.py` | 端口 5740→6002 |
| `application/test/all_in_one/conftest.py` | 端口 5741→6003 |
| `application/test/all_in_one/test_e2e_playwright.py` | 端口 5741→6003 |
| `.github/workflows/test.yml` | 删（release 用 release.yml） |
| `.github/workflows/release.yml` | 端口改为 6000-6004 |

### 不动的文件

- `application/portal/proxy.py` — 端口无关
- `application/portal/update_check.py` — release 保留，demo 不需要但文件可留着不 import
- `application/portal/upgrade.py` — release 保留，demo 不需要但文件可留着不 import
- `tools/build_release.py` — 通用
- `tools/simulate_customer.py` — 仅 main 使用
- 4 个子应用的业务代码 — 不变

---

## Phase 1: main 分支 → Demo 版

### Task 1: 写 demo 版功能差异测试（测试先行）

**Files:**
- Modify: `application/test/portal/test_smoke.py`

这些测试应该先 FAIL（因为端点还没改），改完代码后 PASS。

- [ ] **Step 1: 新增 demo 版端口/功能测试**

在 `application/test/portal/test_smoke.py` 末尾追加：

```python
# ── Demo 版专用测试 ──

DEMO_PORT = 5000
DEMO_SUB_PORTS = (5001, 5002, 5003, 5004)


def test_demo_download_endpoint_exists(portal_running):
    """Demo 版必须保留下载端点。"""
    status, body = http_get(portal_running + "/api/download/latest", timeout=10.0)
    assert status == 200, f"demo 版 /api/download/latest 应返回 200, 实际 {status}"
    data = json.loads(body)
    assert "available" in data


def test_demo_update_check_should_not_exist(portal_running):
    """Demo 版不应有更新检查端点（永远是最新版）。"""
    import urllib.error
    try:
        http_get(portal_running + "/api/update/check", timeout=5.0)
        assert False, "demo 版不应有 /api/update/check"
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"应 404, 实际 {e.code}"


def test_demo_update_upgrade_should_not_exist(portal_running):
    """Demo 版不应有在线升级端点。"""
    import urllib.error
    req = urllib.request.Request(
        portal_running + "/api/update/upgrade",
        data=b'{"download_url":"http://x"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5.0)
        assert False, "demo 版不应有 /api/update/upgrade"
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"应 404, 实际 {e.code}"
```

- [ ] **Step 2: 更新现有测试的端口常量**

将 `test_smoke.py` 中 `PORT = 5000` 不变，`SUB_PORTS = (5001, 5002, 5003, 5004)`。

```python
# 文件顶部常量修改
PORT = 5000
SUB_PORTS = (5001, 5002, 5003, 5004)
```

- [ ] **Step 3: 运行测试确认 FAIL**

```bash
cd application/test
py -3 -m pytest portal/test_smoke.py -v -k "demo"
```
Expected: `test_demo_update_check_should_not_exist` FAIL、`test_demo_update_upgrade_should_not_exist` FAIL（端点目前还存在）

---

### Task 2: 修改 process_manager.py — demo 端口

**Files:**
- Modify: `application/portal/process_manager.py:27-60`

- [ ] **Step 1: 修改 APPS 端口**

```python
APPS = [
    {
        "id": "all_in_one",
        "name": "配置生成",
        "cwd": os.path.join(BASE, "application", "all_in_one - cc", "web"),
        "cmd": [PYTHON, "app.py"],
        "port": 5003,
        "url": "/app/all_in_one/",
    },
    {
        "id": "test_report",
        "name": "测试报告",
        "cwd": os.path.join(BASE, "application", "自动做测试报告 - cc"),
        "cmd": [PYTHON, "app.py"],
        "port": 5002,
        "url": "/app/test_report/",
    },
    {
        "id": "domain_capture",
        "name": "域名抓取",
        "cwd": os.path.join(BASE, "application", "自动抓域名发2"),
        "cmd": [PYTHON, "app.py"],
        "port": 5001,
        "url": "/app/domain_capture/",
    },
    {
        "id": "config_analyzer",
        "name": "配置梳理",
        "cwd": os.path.join(BASE, "application", "自动梳理配置 - cc"),
        "cmd": [PYTHON, "-m", "http.server", "5004"],
        "port": 5004,
        "url": "/app/config_analyzer/er_config_analyzer.html",
    },
]
```

---

### Task 3: 修改 app.py — demo 版功能开关

**Files:**
- Modify: `application/portal/app.py`

- [ ] **Step 1: 删除 update_check/upgrade 导入，删除相关端点，删除 /api/shutdown**

```python
"""Portal Flask app — unified shell + reverse proxy for all sub-apps on port 5000 (demo)."""
import json
import os
import sys
import threading
import webbrowser
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, abort, jsonify, render_template, request, send_file
import process_manager
import proxy
# DEMO: 不导入 update_check 和 upgrade

app = Flask(__name__)

_PORT_MAP = {a["id"]: a["port"] for a in process_manager.APPS}

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DIST_DIR = _PROJECT_ROOT / "dist"


def _find_latest_release():
    """扫描 dist/*.zip，返回最新一份合法包的元数据；不存在或非法则返回 None。"""
    if not _DIST_DIR.is_dir():
        return None
    zips = sorted(_DIST_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return None
    latest = zips[0]

    meta = None
    try:
        with zipfile.ZipFile(latest) as zf:
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    with zf.open(name) as f:
                        meta = json.loads(f.read().decode("utf-8"))
                    break
    except (zipfile.BadZipFile, OSError, ValueError, json.JSONDecodeError):
        return None
    if meta is None:
        return None

    size = latest.stat().st_size
    return {
        "available": True,
        "filename": latest.name,
        "size": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "version": meta.get("version"),
        "built_at": meta.get("built_at"),
        "mtime": int(latest.stat().st_mtime),
    }


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps))


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


@app.route("/api/download/latest")
def api_download_latest():
    """返回最新可分发包的元数据；本地无包时返回 {"available": false}。"""
    info = _find_latest_release()
    if info is None:
        return jsonify({"available": False})
    return jsonify(info)


@app.route("/download/latest.zip")
def download_latest_zip():
    """下发最新可分发包；本地无包时 404。"""
    info = _find_latest_release()
    if info is None:
        abort(404, description="本地暂无可分发 zip，请先在项目根运行 python tools/build_release.py")
    file_path = _DIST_DIR / info["filename"]
    return send_file(
        file_path,
        as_attachment=True,
        download_name=info["filename"],
        mimetype="application/zip",
    )


# ── Reverse proxy for sub-apps ──────────────────────────────────────────

@app.route("/app/<app_id>/", defaults={"subpath": ""}, methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@app.route("/app/<app_id>/<path:subpath>", methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def proxy_route(app_id, subpath):
    if app_id == "config_analyzer":
        if not subpath:
            from flask import redirect
            return redirect(f"/app/{app_id}/er_config_analyzer.html")
    return proxy.proxy_to(app_id, subpath, _PORT_MAP)


def main():
    process_manager.start_all()
    threading.Timer(2.5, lambda: webbrowser.open("http://localhost:5000")).start()
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
```

---

### Task 4: 修改 index.html — demo 版：删更新横幅，保留下载

**Files:**
- Modify: `application/portal/templates/index.html`

- [ ] **Step 1: 删除更新横幅 HTML（约 284-293 行附近）**

删除整个 `<div class="update-banner" id="updateBanner">...</div>` 块。

- [ ] **Step 2: 删除更新横幅 CSS（约 220-268 行附近）**

删除所有 `.update-banner` 相关 CSS 规则。

- [ ] **Step 3: 删除更新/升级 JS**

删除 JS 中的更新检查逻辑（`fetch('/api/update/check')` 及 `showBanner`、`ubUpgrade` 相关代码），保留下载卡片 JS（`fetch('/api/download/latest')` 部分）。

---

### Task 5: 修改 update_config.json — demo 版

**Files:**
- Modify: `application/portal/update_config.json`

```json
{
  "github_repo": "",
  "mirror_url": "",
  "timeout_seconds": 5,
  "cache_ttl_seconds": 3600,
  "user_agent": "5mins-portal-demo"
}
```

---

### Task 6: 修改 start_all.bat — demo 端口

**Files:**
- Modify: `start_all.bat`

端口列表改为 `5003 5002 5001 5004 5000`，portal URL 保持 `http://localhost:5000`。

---

### Task 7: 更新其余 smoke 测试端口

**Files:**
- Modify: `application/test/config_analyzer/test_smoke.py` — port 5742 → 5004
- Modify: `application/test/domain_capture/test_smoke.py` — port 5739 → 5001
- Modify: `application/test/test_report/test_smoke.py` — port 5740 → 5002
- Modify: `application/test/all_in_one/conftest.py` — port 5741 → 5003

每个文件中的端口常量/硬编码改为对应新端口。

---

### Task 8: 更新 Playwright E2E — demo 端口

**Files:**
- Modify: `application/test/all_in_one/test_e2e_playwright.py`

文件中 URL `http://127.0.0.1:5741` → `http://127.0.0.1:5003`。

---

### Task 9: 跑 demo 版全量测试

```bash
cd application/test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py -v
```
Expected: 全部通过（含 demo 端点测试）

```bash
cd application/test/all_in_one
py -3 test_e2e_playwright.py --quick
```
Expected: 42/42

---

### Task 10: Commit demo 版

```bash
git add -A
git commit -m "feat: demo 版 (main 分支) — 端口 5000-5004，有下载无更新"
```

---

## Phase 2: release 分支 → 交付版

### Task 11: 创建 release 分支

```bash
git checkout -b release
```

### Task 12: 修改 process_manager.py — release 端口

**Files:**
- Modify: `application/portal/process_manager.py`

APPS 端口全部改为 6001-6004：
```python
"port": 6003,  # all_in_one
"port": 6002,  # test_report
"port": 6001,  # domain_capture
"port": 6004,  # config_analyzer
```

---

### Task 13: 修改 app.py — release 版功能开关

**Files:**
- Modify: `application/portal/app.py`

与 Task 3 相反：保留 `update_check`/`upgrade` 导入和端点，删除 `_find_latest_release`、`/api/download/latest`、`/download/latest.zip`。端口 6000。user_agent 改为 `5mins-portal-release`。

```python
"""Portal Flask app — unified shell + reverse proxy for all sub-apps on port 6000 (release)."""
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, abort, jsonify, render_template, request, send_file
import process_manager
import proxy
import update_check
import upgrade

app = Flask(__name__)

_PORT_MAP = {a["id"]: a["port"] for a in process_manager.APPS}


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps))


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


@app.route("/api/update/check")
def api_update_check():
    force = request.args.get("force") in ("1", "true", "yes")
    return jsonify(update_check.check(force=force))


@app.route("/api/update/manifest")
def api_update_manifest():
    info = _find_latest_release()
    if info is None:
        return jsonify({
            "error": "no_release_available",
            "message": "本机 dist/ 内没有合法 zip 包",
        }), 404

    base = request.host_url.rstrip("/")
    return jsonify({
        "version": info["version"],
        "release_url": f"{base}/",
        "download_url": f"{base}/download/latest.zip",
        "filename": info["filename"],
        "size_bytes": info["size"],
        "built_at": info.get("built_at"),
    })


@app.route("/download/latest.zip")
def download_latest_zip():
    info = _find_latest_release()
    if info is None:
        abort(404, description="本地暂无可分发 zip")
    file_path = _DIST_DIR / info["filename"]
    return send_file(
        file_path,
        as_attachment=True,
        download_name=info["filename"],
        mimetype="application/zip",
    )


@app.route("/api/update/upgrade", methods=["POST"])
def api_update_upgrade():
    data = request.get_json(silent=True) or {}
    download_url = (data.get("download_url") or "").strip()
    if not download_url:
        return jsonify({"ok": False, "error": "缺少 download_url"}), 400
    result = upgrade.perform_upgrade(download_url)
    if result["ok"]:
        return jsonify(result)
    return jsonify(result), 500


@app.route("/api/shutdown", methods=["POST"])
def api_shutdown():
    threading.Thread(target=_shutdown, daemon=False).start()
    return jsonify({"ok": True, "message": "portal 正在关闭"})


def _shutdown():
    import time as _time
    _time.sleep(0.5)
    process_manager.shutdown_all()
    os._exit(0)


def _find_latest_release():
    """扫描 dist/*.zip，返回最新一份合法包的元数据。"""
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    _DIST_DIR = _PROJECT_ROOT / "dist"
    if not _DIST_DIR.is_dir():
        return None
    import zipfile as _zf
    zips = sorted(_DIST_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        return None
    latest = zips[0]
    meta = None
    try:
        with _zf.ZipFile(latest) as zf:
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    with zf.open(name) as f:
                        meta = json.loads(f.read().decode("utf-8"))
                    break
    except (_zf.BadZipFile, OSError, ValueError, json.JSONDecodeError):
        return None
    if meta is None:
        return None
    size = latest.stat().st_size
    return {
        "available": True,
        "filename": latest.name,
        "size": size,
        "size_mb": round(size / 1024 / 1024, 2),
        "version": meta.get("version"),
        "built_at": meta.get("built_at"),
        "mtime": int(latest.stat().st_mtime),
    }


# ── Reverse proxy for sub-apps ──────────────────────────────────────────

@app.route("/app/<app_id>/", defaults={"subpath": ""}, methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
@app.route("/app/<app_id>/<path:subpath>", methods=[
    "GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
def proxy_route(app_id, subpath):
    if app_id == "config_analyzer":
        if not subpath:
            from flask import redirect
            return redirect(f"/app/{app_id}/er_config_analyzer.html")
    return proxy.proxy_to(app_id, subpath, _PORT_MAP)


def main():
    process_manager.start_all()
    threading.Timer(2.5, lambda: webbrowser.open("http://localhost:6000")).start()
    try:
        app.run(host="0.0.0.0", port=6000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
```

---

### Task 14: 修改 index.html — release 版：保留更新，删下载

**Files:**
- Modify: `application/portal/templates/index.html`

- 保留：更新横幅 HTML+CSS+JS、"在线升级"按钮
- 删除：下载卡片 HTML（`dlCard`）、下载卡片 CSS、`fetch('/api/download/latest')` JS

---

### Task 15: 修改 update_config.json — release 版

```json
{
  "github_repo": "",
  "mirror_url": "",
  "timeout_seconds": 5,
  "cache_ttl_seconds": 3600,
  "user_agent": "5mins-portal-release"
}
```

---

### Task 16: 修改 start_all.bat — release 端口

端口列表改为 `6003 6002 6001 6004 6000`，portal URL 改为 `http://localhost:6000`。

---

### Task 17: 写 release 版功能差异测试（测试先行）

**Files:**
- Modify: `application/test/portal/test_smoke.py`

- [ ] **Step 1: 更新端口常量**

```python
PORT = 6000
SUB_PORTS = (6001, 6002, 6003, 6004)
```

- [ ] **Step 2: 替换 demo 测试为 release 测试**

```python
# ── Release 版专用测试 ──

def test_release_update_check_endpoint_exists(portal_running):
    """Release 版必须有更新检查端点。"""
    status, body = http_get(portal_running + "/api/update/check", timeout=10.0)
    assert status == 200, f"release 版 /api/update/check 应返回 200, 实际 {status}"
    data = json.loads(body)
    assert "status" in data
    assert "has_update" in data


def test_release_update_upgrade_endpoint_exists(portal_running):
    """Release 版必须有在线升级端点。"""
    import urllib.request as _ur
    req = _ur.Request(
        portal_running + "/api/update/upgrade",
        data=b'{"download_url":"http://127.0.0.1:6000/download/latest.zip"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = _ur.urlopen(req, timeout=10.0)
        assert resp.status in (200, 500), f"应 200 或 500, 实际 {resp.status}"
    except _ur.HTTPError as e:
        assert e.code != 404, "release 版不应 404"


def test_release_download_latest_should_not_exist(portal_running):
    """Release 版不应有下载端点（客户不需要打包功能）。"""
    import urllib.error
    try:
        http_get(portal_running + "/api/download/latest", timeout=5.0)
        assert False, "release 版不应有 /api/download/latest"
    except urllib.error.HTTPError as e:
        assert e.code == 404, f"应 404, 实际 {e.code}"
```

---

### Task 18: 更新其余 smoke 测试端口 — release

**Files:**
- Modify: `application/test/config_analyzer/test_smoke.py` — port → 6004
- Modify: `application/test/domain_capture/test_smoke.py` — port → 6001
- Modify: `application/test/test_report/test_smoke.py` — port → 6002
- Modify: `application/test/all_in_one/conftest.py` — port → 6003
- Modify: `application/test/all_in_one/test_e2e_playwright.py` — URL → `http://127.0.0.1:6003`

---

### Task 19: 跑 release 版全量测试

```bash
cd application/test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py -v
```
Expected: 全部通过（含 release 端点测试）

---

### Task 20: Commit release 版

```bash
git add -A
git commit -m "feat: release 版 (release 分支) — 端口 6000-6004，有更新无下载"
```

---

## Phase 3: GitHub Actions

### Task 21: 修改 test.yml — 仅 main 触发

**Files:**
- Modify: `.github/workflows/test.yml`

- [ ] **Step 1: 端口相关配置改为 5000-5004**

在 `Start Xvfb` 步骤后、Run pytest 前，确认 working-directory 为 `application/test`，测试使用端口 5000-5004（通过 smoke 测试代码中的端口常量）。

- [ ] **Step 2: 确保只触发 main**

```yaml
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
```

---

### Task 22: 创建 release.yml — release 分支

**Files:**
- Create: `.github/workflows/release.yml`

完整内容同原 release.yml，但端口改为 6000-6004，触发分支改为 `release`：

```yaml
name: release

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:
    inputs:
      version:
        description: "手动触发时使用的版本号"
        required: true
        default: "v0.0.0-manual"

permissions:
  contents: write

jobs:
  test-and-build:
    name: Test & publish release zip
    runs-on: windows-latest
    timeout-minutes: 30

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          ref: release
          fetch-depth: 0

      - name: Set up Python 3.13
        uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          python -m pip install flask pytest psutil dnspython python-docx Pillow paramiko

      - name: Run release tests (port 6000-6004)
        working-directory: application/test
        env:
          TEST_MODE: "1"
          NO_BROWSER: "1"
        run: |
          python -m pytest --deselect all_in_one/test_e2e_playwright.py -q

      - name: Resolve version
        id: ver
        shell: bash
        run: |
          if [ "${{ github.event_name }}" = "workflow_dispatch" ]; then
            echo "version=${{ github.event.inputs.version }}" >> "$GITHUB_OUTPUT"
          else
            echo "version=${GITHUB_REF_NAME}" >> "$GITHUB_OUTPUT"
          fi

      - name: Build zip (with bundled runtime)
        env:
          PYTHONIOENCODING: utf-8
        run: |
          python tools/build_release.py --version "${{ steps.ver.outputs.version }}"

      - name: Upload artifact
        uses: actions/upload-artifact@v4
        with:
          name: release-zip
          path: dist/*.zip
          if-no-files-found: error
          retention-days: 30

      - name: Publish GitHub Release
        if: github.event_name == 'push'
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ github.ref_name }}
          name: ${{ github.ref_name }}
          generate_release_notes: true
          files: dist/*.zip
          fail_on_unmatched_files: true
```

---

## Phase 4: 最终集成验证

### Task 23: 同时启动两版验证零冲突

- [ ] **Step 1: 切到 main 分支，启动 demo 版**

```bash
git checkout main
cd application/portal && py -3 app.py &
sleep 10
```

验证：`curl http://127.0.0.1:5000/` → 200，`curl http://127.0.0.1:5000/api/download/latest` → 200，`curl http://127.0.0.1:5000/api/update/check` → 404。

- [ ] **Step 2: 切到 release 分支，同时启动 release 版**

```bash
git checkout release
cd application/portal && py -3 app.py &
sleep 10
```

验证：`curl http://127.0.0.1:6000/` → 200，`curl http://127.0.0.1:6000/api/update/check` → 200，`curl http://127.0.0.1:6000/api/download/latest` → 404。

- [ ] **Step 3: 确认两版同时在线，互不冲突**

```bash
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5000/  # 200
curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:6000/  # 200
for port in 5001 5002 5003 5004 6001 6002 6003 6004; do
  curl -s -o /dev/null -w ":$port %{http_code} " http://127.0.0.1:$port/
done
```
Expected: 全部 200

- [ ] **Step 5: 清理所有进程**

```bash
pkill -f "python.*app.py" || true
```

---

## Phase 5: 切回 main + 验收

### Task 24: 最终验收

切回 main 分支，跑 demo 版全量测试（确保 release 分支的修改没污染 main）：

```bash
git checkout main
cd application/test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py -q
```
Expected: 全部通过

---

## 验收清单

- [ ] main 分支：demo 版端口 5000-5004，有下载无更新
- [ ] release 分支：交付版端口 6000-6004，有更新无下载
- [ ] 两版同时启动互不冲突
- [ ] demo 版全量测试通过
- [ ] release 版全量测试通过
- [ ] test.yml 仅 main 触发
- [ ] release.yml 仅 release 触发，含测试+打包+发布
