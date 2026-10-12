# 门户整合 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个门户 Flask 应用，左侧侧栏 + iframe 主内容区，统一展示和使用四个现有子应用，启动门户时自动拉起并守护四个子应用进程。

**Architecture:** 新建 `portal/` 目录，包含 Flask 门户应用 (`app.py`)、进程管理器 (`process_manager.py`)、HTML 模板。门户在端口 5000 上运行，通过 iframe 嵌入四个子应用 (localhost:5739-5742)。进程管理器在门户启动时 spawn 四个子进程，定期健康检查，崩溃自动重启，门户退出时统一清理。

**Tech Stack:** Python 3.13 + Flask + Vanilla HTML/CSS/JS，严格遵循 DESIGN.md (Cursor 设计系统)

---

## File Structure

```
帮你节省5分钟/
├── portal/                        # 新建：门户应用
│   ├── app.py                     # Flask 门户入口，路由 + 启动逻辑
│   ├── process_manager.py         # 子进程管理器（启动/监控/重启/清理）
│   └── templates/
│       └── index.html             # 门户页面（侧栏 + iframe）
├── start_all.bat                  # 新建：一键启动脚本
├── plan/
│   └── portal-integration.md      # 本文件
└── log/                           # 已有：修改日志目录
```

---

### Task 1: 创建进程管理器 `portal/process_manager.py`

**Files:**
- Create: `portal/process_manager.py`

**职责：** 管理四个子应用的生命周期 — 启动、健康检查、崩溃重启、优雅关闭。

- [ ] **Step 1: 编写进程管理器模块**

```python
"""Sub-application process manager — spawn, health-check, restart, cleanup."""
import subprocess
import sys
import time
import socket
import atexit
import threading
import os

BASE = r"C:\Users\123\Desktop\帮你节省5分钟"
PYTHON = sys.executable

APPS = [
    {
        "id": "all_in_one",
        "name": "配置生成",
        "cwd": os.path.join(BASE, "all_in_one - cc", "web"),
        "cmd": [PYTHON, "app.py"],
        "port": 5741,
        "url": "http://localhost:5741",
    },
    {
        "id": "test_report",
        "name": "测试报告",
        "cwd": os.path.join(BASE, "自动做测试报告 - cc"),
        "cmd": [PYTHON, "app.py"],
        "port": 5740,
        "url": "http://localhost:5740",
    },
    {
        "id": "domain_capture",
        "name": "域名抓取",
        "cwd": os.path.join(BASE, "自动抓域名发2"),
        "cmd": [PYTHON, "app.py"],
        "port": 5739,
        "url": "http://localhost:5739",
    },
    {
        "id": "config_analyzer",
        "name": "配置梳理",
        "cwd": os.path.join(BASE, "自动梳理配置 - cc"),
        "cmd": [PYTHON, "-m", "http.server", "5742"],
        "port": 5742,
        "url": "http://localhost:5742/er_config_analyzer.html",
    },
]

_processes = {}   # app_id -> subprocess.Popen
_running = True


def _port_open(port: str, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """Check if a TCP port is accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _wait_for_port(port, timeout=30.0) -> bool:
    """Block until port is open or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _port_open(port):
            return True
        time.sleep(0.5)
    return False


def _monitor_loop():
    """Background thread: restart any app whose process has died."""
    global _running
    while _running:
        for app in APPS:
            proc = _processes.get(app["id"])
            if proc is None:
                continue
            if proc.poll() is not None:
                print(f"[portal] {app['name']} (port {app['port']}) exited, restarting...")
                _start_one(app)
        time.sleep(3)


def _start_one(app: dict) -> None:
    """Start a single sub-app process."""
    try:
        proc = subprocess.Popen(
            app["cmd"],
            cwd=app["cwd"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _processes[app["id"]] = proc
        print(f"[portal] Starting {app['name']} (pid={proc.pid}, port={app['port']})...")
        if _wait_for_port(app["port"], timeout=15.0):
            print(f"[portal] {app['name']} ready at {app['url']}")
        else:
            print(f"[portal] WARNING: {app['name']} port {app['port']} not reachable after 15s")
    except Exception as e:
        print(f"[portal] ERROR starting {app['name']}: {e}")


def start_all() -> None:
    """Launch all sub-apps and begin monitoring."""
    print("[portal] Starting all sub-applications...")
    for app in APPS:
        _start_one(app)
    monitor = threading.Thread(target=_monitor_loop, daemon=True)
    monitor.start()


def shutdown_all() -> None:
    """Terminate all sub-app processes."""
    global _running
    _running = False
    for app_id, proc in _processes.items():
        if proc.poll() is None:
            print(f"[portal] Stopping {app_id} (pid={proc.pid})...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print(f"[portal] Force-killing {app_id}")
                proc.kill()
    print("[portal] All sub-apps stopped.")


def get_apps_status() -> list[dict]:
    """Return list of apps with their current status for the frontend."""
    result = []
    for app in APPS:
        proc = _processes.get(app["id"])
        alive = proc is not None and proc.poll() is None
        reachable = _port_open(app["port"]) if alive else False
        result.append({
            "id": app["id"],
            "name": app["name"],
            "url": app["url"],
            "port": app["port"],
            "alive": alive,
            "reachable": reachable,
        })
    return result


# Register cleanup on normal exit
atexit.register(shutdown_all)
```

- [ ] **Step 2: 验证模块可以导入**

```powershell
cd "C:\Users\123\Desktop\帮你节省5分钟\portal"
py -3 -c "import process_manager; print('OK'); print(process_manager.APPS)"
```

Expected: 打印四个应用配置，无报错。

---

### Task 2: 创建门户 HTML 模板 `portal/templates/index.html`

**Files:**
- Create: `portal/templates/index.html`

**职责：** 左侧侧栏（应用列表 + 状态指示）+ 右侧 iframe 内容区。样式严格遵循 DESIGN.md。

- [ ] **Step 1: 编写完整 HTML 模板**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Network Tools</title>
<style>
  :root {
    --primary: #f54e00;
    --primary-active: #d04200;
    --ink: #26251e;
    --body: #5a5852;
    --muted: #807d72;
    --hairline: #e6e5e0;
    --canvas: #f7f7f4;
    --surface-card: #ffffff;
    --surface-strong: #e6e5e0;
    --semantic-success: #1f8a65;
    --semantic-error: #cf2d56;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Inter', system-ui, 'Helvetica Neue', Helvetica, Arial, sans-serif;
    background: var(--canvas);
    color: var(--ink);
    height: 100vh;
    overflow: hidden;
  }

  .layout {
    display: flex;
    height: 100vh;
  }

  /* ---- Sidebar ---- */
  .sidebar {
    width: 240px;
    min-width: 240px;
    background: var(--surface-card);
    border-right: 1px solid var(--hairline);
    display: flex;
    flex-direction: column;
    user-select: none;
  }

  .sidebar-header {
    padding: 20px 20px 16px;
    border-bottom: 1px solid var(--hairline);
  }

  .sidebar-header h1 {
    font-size: 16px;
    font-weight: 600;
    color: var(--ink);
    letter-spacing: -0.11px;
  }

  .sidebar-header p {
    font-size: 11px;
    font-weight: 400;
    color: var(--muted);
    margin-top: 4px;
    letter-spacing: 0.88px;
    text-transform: uppercase;
  }

  .app-list {
    flex: 1;
    padding: 8px;
    overflow-y: auto;
  }

  .app-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 12px;
    border-radius: 8px;
    cursor: pointer;
    transition: background 0.15s;
    text-decoration: none;
    color: var(--ink);
    border: 1px solid transparent;
    margin-bottom: 2px;
  }

  .app-item:hover {
    background: #fafaf7;
  }

  .app-item.active {
    background: #fafaf7;
    border-color: var(--hairline);
  }

  .app-item.active .app-indicator {
    background: var(--primary);
  }

  .app-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--hairline);
    flex-shrink: 0;
  }

  .app-indicator.online {
    background: var(--semantic-success);
  }

  .app-indicator.offline {
    background: var(--semantic-error);
  }

  .app-item.active .app-indicator.online {
    background: var(--primary);
  }

  .app-label {
    flex: 1;
    font-size: 14px;
    font-weight: 500;
    line-height: 1.4;
  }

  .app-badge {
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 9999px;
    background: var(--surface-strong);
    color: var(--muted);
  }

  .app-item.active .app-badge {
    background: var(--primary);
    color: #ffffff;
  }

  .sidebar-footer {
    padding: 12px 20px;
    border-top: 1px solid var(--hairline);
    font-size: 11px;
    color: var(--muted);
  }

  /* ---- Main Content ---- */
  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    background: var(--canvas);
  }

  .main-header {
    height: 48px;
    min-height: 48px;
    display: flex;
    align-items: center;
    padding: 0 24px;
    border-bottom: 1px solid var(--hairline);
    background: var(--surface-card);
  }

  .main-header .current-app {
    font-size: 14px;
    font-weight: 500;
    color: var(--ink);
  }

  .main-header .current-app span {
    color: var(--muted);
    font-weight: 400;
    margin-left: 6px;
    font-size: 12px;
  }

  .frame-wrap {
    flex: 1;
    position: relative;
  }

  .frame-wrap iframe {
    width: 100%;
    height: 100%;
    border: none;
  }

  .frame-placeholder {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    color: var(--muted);
    pointer-events: none;
  }

  .frame-placeholder .ph-icon {
    font-size: 48px;
    margin-bottom: 16px;
    opacity: 0.3;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }

  .frame-placeholder .ph-text {
    font-size: 14px;
    font-weight: 400;
  }
</style>
</head>
<body>

<div class="layout">

  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <h1>Network Tools</h1>
      <p>Console</p>
    </div>
    <nav class="app-list" id="appList">
      {% for app in apps %}
      <a class="app-item" href="#" data-id="{{ app.id }}" data-url="{{ app.url }}">
        <span class="app-indicator {{ 'online' if app.reachable else 'offline' }}"></span>
        <span class="app-label">{{ app.name }}</span>
        <span class="app-badge">:{{ app.port }}</span>
      </a>
      {% endfor %}
    </nav>
    <div class="sidebar-footer" id="statusFooter">
      {{ online_count }}/{{ total_count }} services online
    </div>
  </aside>

  <!-- Main -->
  <main class="main">
    <div class="main-header">
      <div class="current-app" id="currentAppLabel">
        Select an application <span>— choose from the sidebar</span>
      </div>
    </div>
    <div class="frame-wrap" id="frameWrap">
      <div class="frame-placeholder" id="placeholder">
        <div class="ph-icon">&lt;/&gt;</div>
        <div class="ph-text">Select an application to begin</div>
      </div>
      <iframe id="appFrame" style="display:none" src="" sandbox="allow-scripts allow-same-origin allow-forms allow-popups"></iframe>
    </div>
  </main>

</div>

<script>
(function() {
  var items = document.querySelectorAll('.app-item');
  var frame = document.getElementById('appFrame');
  var placeholder = document.getElementById('placeholder');
  var label = document.getElementById('currentAppLabel');
  var currentId = null;

  function activate(item) {
    items.forEach(function(el) { el.classList.remove('active'); });
    item.classList.add('active');
    var id = item.dataset.id;
    var url = item.dataset.url;
    var name = item.querySelector('.app-label').textContent;
    currentId = id;

    label.innerHTML = name + ' <span>— ' + url + '</span>';
    frame.src = url;
    frame.style.display = '';
    placeholder.style.display = 'none';
  }

  items.forEach(function(item) {
    item.addEventListener('click', function(e) {
      e.preventDefault();
      activate(item);
    });
  });

  // Auto-activate first online app, or first app
  var firstOnline = document.querySelector('.app-indicator.online');
  var toActivate = firstOnline ? firstOnline.parentElement : items[0];
  if (toActivate) activate(toActivate);

  // Periodic status refresh via polling
  setInterval(function() {
    fetch('/api/status')
      .then(function(r) { return r.json(); })
      .then(function(apps) {
        items.forEach(function(item) {
          var app = apps.find(function(a) { return a.id === item.dataset.id; });
          if (!app) return;
          var dot = item.querySelector('.app-indicator');
          dot.className = 'app-indicator ' + (app.reachable ? 'online' : 'offline');
        });
        var online = apps.filter(function(a) { return a.reachable; }).length;
        document.getElementById('statusFooter').textContent = online + '/' + apps.length + ' services online';
      })
      .catch(function() { /* portal itself is fine, ignore */ });
  }, 10000);
})();
</script>

</body>
</html>
```

- [ ] **Step 2: 验证模板文件存在**

```powershell
Test-Path "C:\Users\123\Desktop\帮你节省5分钟\portal\templates\index.html"
```

Expected: `True`

---

### Task 3: 创建 Flask 门户入口 `portal/app.py`

**Files:**
- Create: `portal/app.py`

**职责：** Flask 应用，提供门户页面路由 `/` 和状态 API `/api/status`。启动时调用 process_manager 拉起子应用。

- [ ] **Step 1: 编写 Flask 应用**

```python
"""Portal Flask app — unified shell for four network-tool sub-applications."""
import sys
import os

# Ensure portal/ is on sys.path so we can import process_manager
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask, render_template, jsonify
import process_manager

app = Flask(__name__)


@app.route("/")
def index():
    apps = process_manager.get_apps_status()
    online_count = sum(1 for a in apps if a["reachable"])
    return render_template("index.html", apps=apps, online_count=online_count, total_count=len(apps))


@app.route("/api/status")
def api_status():
    return jsonify(process_manager.get_apps_status())


def main():
    process_manager.start_all()
    try:
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        process_manager.shutdown_all()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 测试 Flask 应用能否导入**

```powershell
cd "C:\Users\123\Desktop\帮你节省5分钟\portal"
py -3 -c "from app import app; print('Flask app imported OK')"
```

Expected: `Flask app imported OK`

---

### Task 4: 创建一键启动脚本 `start_all.bat`

**Files:**
- Create: `start_all.bat`

- [ ] **Step 1: 编写启动脚本**

```batch
@echo off
cd /d "%~dp0"
echo ============================================
echo   Network Tools Portal
echo   Starting all services...
echo ============================================
echo.
echo   Portal:      http://localhost:5000
echo   Config Gen:  http://localhost:5741
echo   Test Report: http://localhost:5740
echo   DNS Capture: http://localhost:5739
echo   Config Ana:  http://localhost:5742
echo.
echo   Press Ctrl+C in this window to stop all services.
echo ============================================
echo.

cd portal
py -3 app.py
```

- [ ] **Step 2: 验证脚本路径正确**

```powershell
Get-Content "C:\Users\123\Desktop\帮你节省5分钟\start_all.bat"
```

Expected: 打印上述脚本内容。

---

### Task 5: 端到端集成测试

- [ ] **Step 1: 启动门户并验证**

```powershell
# 在后台启动门户
Start-Process -FilePath "py" -ArgumentList "-3", "app.py" -WorkingDirectory "C:\Users\123\Desktop\帮你节省5分钟\portal" -WindowStyle Hidden
Start-Sleep -Seconds 8
```

- [ ] **Step 2: 验证门户页面可访问**

```powershell
curl -s http://localhost:5000/ | Select-String -Pattern "Network Tools"
```

Expected: 匹配到 "Network Tools"。

- [ ] **Step 3: 验证状态 API**

```powershell
curl -s http://localhost:5000/api/status
```

Expected: JSON 数组，包含四个应用的状态信息。

- [ ] **Step 4: 验证子应用端口可达**

```powershell
curl -s -o $null -w "%{http_code}" http://localhost:5741
curl -s -o $null -w "%{http_code}" http://localhost:5740
curl -s -o $null -w "%{http_code}" http://localhost:5739
curl -s -o $null -w "%{http_code}" http://localhost:5742/er_config_analyzer.html
```

Expected: 四个端口均返回 HTTP 200。

- [ ] **Step 5: 清理测试进程**

```powershell
# 找到并停止门户进程（它会自动清理子进程）
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -eq "" } | Stop-Process -Force -ErrorAction SilentlyContinue
```

---

### Task 6: 记录修改日志

**Files:**
- Create/Append: `log/2026-05-21.md`

- [ ] **Step 1: 追加修改日志**

内容：

```
## 2026-05-21

### 14:30
- 文件: `portal/app.py`, `portal/process_manager.py`, `portal/templates/index.html`, `start_all.bat`
- 说明: 创建门户整合应用。Flask 外壳 + 侧栏导航 + iframe 嵌入四个子应用。进程管理器自动拉起并守护子进程。严格遵循 DESIGN.md 样式规范。
```
