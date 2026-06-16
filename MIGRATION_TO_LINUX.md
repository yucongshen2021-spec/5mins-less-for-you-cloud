# 帮你节省5分钟 — 迁移到 Linux/Docker 完整方案

> **文档性质**：纯实施蓝图，不含代码改动。按本文档可独立完成全部迁移。  
> **目标环境**：Linux 云服务器（ECS）+ Docker Compose 单容器部署  
> **预估工作量**：3-4 天（1 人）

---

## 一、架构现状与核心矛盾

### 1.1 当前架构（Windows 绑定）

| 模块 | 端口 | 技术栈 | Windows 绑定点 |
|------|------|--------|----------------|
| **Portal** | 5000/7000 | Flask + 反向代理 | `noop.cmd`、进程管理、`.bat` 升级脚本 |
| **配置生成** | 5003/7003 | Flask + tkinter(exec) | `tk.Tk()` 需 DISPLAY、PyInstaller 路径逻辑 |
| **测试报告** | 5002/7002 | Flask + Playwright + docx | `subprocess.Popen` 继承 stdin TTY |
| **域名抓取** | 5001/7001 | Flask + Playwright + DNS | 浏览器扫描硬编码 Windows 路径 |
| **配置梳理** | 5004/7004 | Flask (纯静态) | 无特殊绑定 |

### 1.2 核心矛盾清单

1. **进程管理**：`process_manager.py` 用 `netstat -ano` + `taskkill` 管理进程，Linux 下完全失效。
2. **启动脚本**：`start_all.bat` 是纯 Windows 批处理，无 Linux 等价物。
3. **升级系统**：`upgrade.py` 生成 `.bat` 脚本做在线升级，Linux 无法执行。
4. **Playwright**：域名抓取和测试报告依赖 Chromium，Linux 需要 `xvfb` + 系统依赖。
5. **tkinter**：配置生成模块通过 `exec()` 加载含 `tk.Tk()` 的代码，无头 Linux 会崩溃。
6. **浏览器路径**：域名抓取扫描 `C:\Program Files\...` 等 Windows 浏览器路径。
7. **stdin 继承**：测试报告 `subprocess.Popen` 未隔离 stdin，非交互环境 `input()` 崩溃（历史错误 #49）。
8. **构建系统**：`build_release.py` 输出 Windows zip，无 Docker 构建流程。
9. **APPDATA**：`all_in_one` 用 `%APPDATA%` 做数据目录，Linux 无此环境变量。

---

## 二、目标架构（Docker 单容器）

```
┌─────────────────────────────────────────────────────┐
│              Docker Container                       │
│  ┌─────────────────────────────────────────────┐   │
│  │  Portal Flask (7000) — 统一入口 + 反向代理    │   │
│  └─────────────┬───────────────────────────────┘   │
│                │                                    │
│  ┌─────────────┼─────────────┬─────────────────┐   │
│  ▼             ▼             ▼                 ▼   │
│ all_in_one  test_report  domain_capture  config    │
│  :7003       :7002        :7001         :7004      │
│                                                    │
│  Supervisor: 管理 5 个进程 + Xvfb (:99)            │
│  Volumes:    持久化用户数据 / 日志                 │
└─────────────────────────────────────────────────────┘
```

**设计决策**：
- 单容器（非微服务）：5 个进程由 `supervisord` 管理，复杂度低，适合当前规模。
- 端口统一走 700x（Release 模式），不再区分 Demo/Release。
- 升级功能在 Docker 环境下**禁用**（由镜像替换代替）。

---

## 三、文件变更总览

### 3.1 新增文件（7 个）

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 容器镜像定义 |
| `docker-compose.yml` | 编排配置（端口映射、卷、健康检查） |
| `.dockerignore` | 构建排除规则 |
| `requirements.txt` | 统一 Python 依赖（合并 5 个模块） |
| `docker/supervisord.conf` | 容器内进程管理 |
| `application/portal/noop.sh` | Linux 无操作浏览器 stub |
| `start_linux.sh` *(可选)* | 裸机部署启动脚本（不用 Docker 时） |

### 3.2 修改文件（6 个）

| 文件 | 修改原因 | 工作量 |
|------|----------|--------|
| `application/portal/process_manager.py` | Linux 进程管理 + Supervisor 模式适配 | 0.5 天 |
| `application/portal/app.py` | 删除/条件化 webbrowser.open()、升级路由 Docker 禁用 | 0.3 天 |
| `application/portal/upgrade.py` | Docker 环境下跳过 bat 生成，或返回"不支持" | 0.3 天 |
| `application/自动抓域名发2/app.py` | Linux Chromium 路径 + headless 强制 | 0.5 天 |
| `application/all_in_one - cc/web/app.py` | DISPLAY 环境检测 + tkinter 容错 | 0.5 天 |
| `application/自动做测试报告 - cc/app.py` | `stdin=subprocess.DEVNULL` 防 TTY 继承 | 0.2 天 |

### 3.3 不修改的文件

- `application/自动梳理配置 - cc/app.py` — 纯静态 Flask，无平台绑定。
- `application/portal/proxy.py` — `urllib.request` 是跨平台的，localhost 代理在容器内可用。
- 所有业务逻辑 `.py`（`all_in_one_v2.py`、`make_report.py` 等）— 不改逻辑，只改入口和调用方式。

---

## 四、逐项实施细节

### 4.1 统一依赖：`requirements.txt`

合并各模块分散的依赖到一个根目录文件：

```text
flask>=3.0
paramiko>=3.4.0
python-docx>=1.1.0
Pillow>=10.0.0
playwright>=1.40.0
dnspython>=2.0
```

**注意**：
- `pyinstaller` 是构建工具，不放在运行时依赖中。
- 各子应用的私有 `requirements.txt`（如 `src/requirements.txt`）保留不动，Docker 只读根目录这份。

---

### 4.2 容器镜像：`Dockerfile`

**基础镜像**：`python:3.11-slim-bookworm`

**系统依赖**：
```dockerfile
RUN apt-get update && apt-get install -y \
    tk xvfb supervisor curl wget gnupg ca-certificates \
    fonts-wqy-zenhei fonts-wqy-microhei \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0
```

**关键层**：
1. `playwright install chromium` — 安装浏览器二进制。
2. `playwright install-deps chromium` — 安装 Chromium 系统库。
3. `ENV DISPLAY=:99` — Xvfb 虚拟显示。
4. `ENV BROWSER=echo` — 禁用 `webbrowser.open()`。
5. `ENV RELEASE_MODE=1` — 强制 Release 端口模式。

**健康检查**：
```dockerfile
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s \
  CMD curl -f http://localhost:7000/api/health || exit 1
```

---

### 4.3 进程管理：`docker/supervisord.conf`

```ini
[supervisord]
nodaemon=true

[program:xvfb]
command=/usr/bin/Xvfb :99 -screen 0 1024x768x24
autorestart=true
priority=10

[program:portal]
command=python /app/application/portal/app.py
environment=RELEASE_MODE="1",DISPLAY=":99",BROWSER="echo",SUPERVISOR_MODE="1"
autorestart=true
priority=20

[program:all_in_one]
command=python "/app/application/all_in_one - cc/web/app.py" 7003
environment=DISPLAY=":99"
autorestart=true
priority=30

; ... 其余 3 个子应用同理
```

**设计要点**：
- `SUPERVISOR_MODE=1` 告诉 portal：子应用已由 supervisord 启动，不要自己 `subprocess.Popen`。
- `priority` 确保 Xvfb 最先启动（tkinter 和 Playwright 都需要 DISPLAY）。
- `stdout_logfile` 统一写到 `/app/application/portal/logs/xxx.log`，方便排障。

---

### 4.4 `process_manager.py` 改造

#### 4.4.1 新增：跨平台进程终止

```python
_IS_WIN = sys.platform == "win32"

# Windows: netstat + taskkill（保留现有逻辑）
# Linux:  fuser -k :port/tcp 或 lsof -ti :port + kill -9
```

#### 4.4.2 新增：Supervisor 模式检测

```python
_SUPERVISOR_MODE = os.environ.get("SUPERVISOR_MODE", "").strip() == "1"
```

当 `_SUPERVISOR_MODE` 为真时：
- `start_all()` 不调用 `subprocess.Popen`，只轮询端口 `_wait_for_port()`。
- `get_apps_status()` 不检查 `proc.poll()`（portal 不持有子进程句柄），直接 `_port_open()`。
- `shutdown_all()` 不 `proc.terminate()`（由 supervisord 负责生命周期）。

#### 4.4.3 修复：`subprocess.Popen` 参数

Linux 非 Supervisor 模式（裸机运行）时：
```python
kwargs = {
    "cwd": app["cwd"],
    "stdout": log_fh,
    "stderr": log_fh,
    "env": _SUB_ENV,
    "stdin": subprocess.DEVNULL,  # 防止 TTY 继承（历史错误 #49）
}
if _IS_WIN:
    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
```

#### 4.4.4 新增：`noop.sh`

```bash
#!/bin/sh
exit 0
```

`process_manager.py` 中 `_NOOP_BROWSER` 按平台选择 `.cmd` 或 `.sh`。

---

### 4.5 `application/portal/app.py` 改造

#### 4.5.1 禁用 `webbrowser.open()`

现有代码在 `app.run()` 前调用 `webbrowser.open()`，Linux 无头环境无意义：

```python
# 原代码
threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

# 改造：条件化
if os.environ.get("BROWSER") not in ("echo", "", "none"):
    threading.Timer(1.5, lambda: webbrowser.open(...)).start()
```

#### 4.5.2 升级路由 Docker 禁用

```python
# /api/update/upgrade 路由
if os.environ.get("SUPERVISOR_MODE") == "1":
    return jsonify({"ok": False, "error": "Docker 环境不支持在线升级，请更新镜像"}), 400
```

Docker 升级策略是**重新构建镜像 + 替换容器**，不是热更新。

---

### 4.6 `application/自动抓域名发2/app.py` 改造

#### 4.6.1 浏览器扫描路径 Linux 化

现有 `_BROWSER_CANDIDATES` 全是 Windows 路径：

```python
# Windows 路径（现有）
("Chrome", [r"C:\Program Files\Google\Chrome\Application\chrome.exe", ...])

# Linux 路径（新增）
("Chromium", ["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"])
```

#### 4.6.2 强制 headless

```python
browser = p.chromium.launch(headless=True)
```

即使代码里不强制，Linux 无 X 环境也会自动 headless，但显式写更稳妥。

---

### 4.7 `application/all_in_one - cc/web/app.py` 改造

#### 4.7.1 问题

第 69 行：
```python
_web_root = tk.Tk()
```

Linux 无 DISPLAY 时抛出 `_tkinter.TclError: no display name and no $DISPLAY environment variable`。

#### 4.7.2 解决方案

Dockerfile 已设置 `DISPLAY=:99` 并启动 Xvfb，所以 `tk.Tk()` 在容器内可以工作。

**但需要增加容错**（裸机运行无 Xvfb 时）：

```python
try:
    _web_root = tk.Tk()
    _web_root.withdraw()
except Exception as e:
    # Fallback: stub Tk for pure logic loading
    import tkinter
    class _StubTk:
        def withdraw(self): pass
        def destroy(self): pass
    _web_root = _StubTk()
    print(f"[warn] tk.Tk() failed ({e}), using stub. UI generation may be limited.")
```

#### 4.7.3 APPDATA 路径

```python
# Windows
_DATA_RW_DIR = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "all_in_one" / "data"

# Linux fallback
_DATA_RW_DIR = Path(os.environ.get("APPDATA", Path.home() / ".config")) / "all_in_one" / "data"
```

在 Docker 中通过 Volume 挂载覆盖此路径到宿主机。

---

### 4.8 `application/自动做测试报告 - cc/app.py` 改造

#### 4.8.1 问题

`api_run()` 中启动 `make_report.py`：

```python
proc = subprocess.Popen(
    [sys.executable, str(SCRIPT), ...],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    # stdin 未设置 → 继承 Flask 进程的 stdin
)
```

当 `make_report.py` 里的 `sys.stdin.isatty()` 返回 True（因为继承了终端 stdin），会进入交互模式调用 `input()` → `EOFError`（历史错误 #49）。

#### 4.8.2 修复

```python
proc = subprocess.Popen(
    [sys.executable, str(SCRIPT), ...],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,  # 隔离 stdin
)
```

**举一反三**：全仓库搜索所有 `subprocess.Popen`，确认用于 web 后台调用的都加了 `stdin=subprocess.DEVNULL`。

---

### 4.9 `upgrade.py` 改造

#### 4.9.1 问题

`upgrade.py` 的核心功能是：
1. 下载新 zip
2. 生成 `update.bat`（Windows 批处理）
3. 启动 bat，portal 自杀，bat 负责解压覆盖 + 重启

Linux 无法执行 `.bat`，整个机制需要重写。

#### 4.9.2 Docker 策略

**方案 A（推荐）：禁用热升级**
- `/api/update/check` — 保留，返回版本信息（只读）。
- `/api/update/upgrade` — 返回 `400`，提示"Docker 环境请更新镜像"。
- 运维通过 `docker pull` + `docker compose up -d` 升级。

**方案 B（裸机部署时）：重写为 bash**
- 生成 `update.sh` 替代 `update.bat`。
- 用 `fuser`/`kill` 替代 `taskkill`。
- 用 `unzip` + `cp -r` 替代 PowerShell `Expand-Archive` + `robocopy`。
- **工作量 +1 天**。

本文档推荐方案 A（Docker），方案 B 在裸机需求出现时再实施。

---

## 五、Docker Compose 部署配置

### 5.1 `docker-compose.yml`

```yaml
services:
  portal:
    build: .
    container_name: fivemins-portal
    ports:
      - "7000:7000"
      - "7001:7001"
      - "7002:7002"
      - "7003:7003"
      - "7004:7004"
    volumes:
      - portal-data:/app/application/all_in_one - cc/data
      - portal-logs:/app/application/portal/logs
      - report-logs:/app/application/自动做测试报告 - cc/log
    environment:
      - RELEASE_MODE=1
      - SUPERVISOR_MODE=1
      - DISPLAY=:99
      - BROWSER=echo
    restart: unless-stopped

volumes:
  portal-data:
  portal-logs:
  report-logs:
```

### 5.2 `.dockerignore`

```gitignore
# 排除 Windows 文件
*.bat
*.cmd
*.exe
*.dll
runtime/

# 排除开发和测试
__pycache__/
.git/
.pytest_cache/
.mypy_cache/
application/test/
plan/
temp/
agent-transcripts/

# 排除日志（运行时生成）
log/
logs/
application/portal/logs/
application/自动做测试报告 - cc/log/

# 排除用户数据（Volume 挂载）
application/all_in_one - cc/data/editor_workspace/
user_init_placeholders.json
.update_cache.json

# 排除构建产物
dist/
.build_cache/
```

---

## 六、裸机部署（不用 Docker 时）

如果用户坚持不用 Docker，需要额外做：

### 6.1 系统依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-tk xvfb \
  chromium-browser fonts-wqy-zenhei supervisor

# Playwright
pip install playwright
playwright install chromium
```

### 6.2 `start_linux.sh`

```bash
#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Kill stale ports
for port in 7000 7001 7002 7003 7004; do
    fuser -k "${port}/tcp" 2>/dev/null || true
done

# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
export RELEASE_MODE=1
export BROWSER=echo

# Start sub-apps in background
cd "application/all_in_one - cc/web"
python3 app.py 7003 &
cd - > /dev/null

cd "application/自动做测试报告 - cc"
python3 app.py 7002 &
cd - > /dev/null

cd "application/自动抓域名发2"
python3 app.py 7001 &
cd - > /dev/null

cd "application/自动梳理配置 - cc"
python3 app.py 7004 &
cd - > /dev/null

# Start portal (foreground)
cd application/portal
python3 app.py
```

### 6.3 Systemd 服务

```ini
# /etc/systemd/system/fivemins.service
[Unit]
Description=5mins Tools Portal
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/帮你节省5分钟
ExecStart=/opt/帮你节省5分钟/start_linux.sh
Restart=on-failure
Environment=DISPLAY=:99
Environment=RELEASE_MODE=1

[Install]
WantedBy=multi-user.target
```

---

## 七、测试验证清单

### 7.1 构建阶段

| 检查项 | 命令 | 通过标准 |
|--------|------|----------|
| 镜像构建 | `docker build -t fivemins .` | 无 ERROR，层缓存正常 |
| 容器启动 | `docker compose up -d` | `docker ps` 显示 healthy |
| 端口监听 | `docker exec fivemins-portal ss -tlnp` | 7000-7004 都在 LISTEN |

### 7.2 功能验证（逐一访问）

| 功能 | URL | 检查点 |
|------|-----|--------|
| Portal 首页 | `http://ECS_IP:7000/` | 标题正确、sidebar 4 个入口 |
| 配置生成 | `http://ECS_IP:7000/app/all_in_one/` | 页面加载、级联菜单可见 |
| 测试报告 | `http://ECS_IP:7000/app/test_report/` | 表单完整、日期默认今天 |
| 域名抓取 | `http://ECS_IP:7000/app/domain_capture/` | 输入框 + 提交按钮 |
| 配置梳理 | `http://ECS_IP:7000/app/domain_capture/` | HTML 渲染正常 |
| 代理连通 | Portal 点击子应用入口 | 不 502，iframe/代理正常 |

### 7.3 子应用深度验证

**配置生成**：
- 选择任意模板 → 填写参数 → 生成配置
- 期望：返回 CLI 配置文本，无 500 错误

**测试报告**（需要 CE 环境）：
- 填写 CE 信息 → 点击"开始生成"
- 期望：SSE 流式日志正常输出，不 `EOFError`

**域名抓取**：
- 输入域名 → 点击"抓取"
- 期望：Playwright 截图成功返回，DNS CNAME 链正确

### 7.4 Playwright 无头验证

```bash
# 进入容器测试
 docker exec -it fivemins-portal bash
 python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(headless=True); print('OK'); b.close(); p.stop()"
```

### 7.5 日志检查

```bash
docker logs fivemins-portal          # portal stdout
docker exec fivemins-portal tail -f /app/application/portal/logs/all_in_one.log
docker exec fivemins-portal tail -f /app/application/portal/logs/domain_capture.log
```

---

## 八、风险与注意事项

### 8.1 高风险项

| 风险 | 影响 | 缓解 |
|------|------|------|
| `tk.Tk()` 在 Xvfb 上仍失败 | 配置生成完全不可用 | Dockerfile 必须装 `tk` + `xvfb`；增加 try/except stub fallback |
| Playwright Chromium 系统依赖缺失 | 域名抓取、测试报告截图失败 | `playwright install-deps chromium` 必须执行，且基础镜像要有足够系统库 |
| `all_in_one` 的 `exec()` 加载业务逻辑时触发 GUI | 子应用崩溃，portal 反复 502 | 加载前 stub `tkinter.mainloop` 等阻塞调用 |

### 8.2 已规避的历史错误

- **#49 stdin 继承**：所有 web 后台 `subprocess.Popen` 统一加 `stdin=subprocess.DEVNULL`。
- **#33 端口替换误伤**：不改 `app.py`/`process_manager.py` 中的 `if _RELEASE else 5000` 字面量（Docker 直接设 `RELEASE_MODE=1`）。
- **#36 bat 编码问题**：Linux 彻底绕过 `.bat`，无编码问题。

### 8.3 数据持久化

| 数据类型 | 容器内路径 | 是否 Volume | 说明 |
|----------|-----------|-------------|------|
| 配置生成工作区 | `.../all_in_one - cc/data/editor_workspace` | ✅ | 用户保存的配置 |
| Portal 日志 | `.../portal/logs/` | ✅ | 排障用 |
| 测试报告日志 | `.../自动做测试报告 - cc/log/` | ✅ | 每次测试生成 |
| 测试报告截图 | `.../自动做测试报告 - cc/log/日期_CID/screenshots/` | ✅ | 需确认路径 |
| 源码 | `/app/...` | ❌ | 镜像内只读 |

---

## 九、分阶段实施建议

### 第一阶段：Docker 骨架（1 天）
1. 写 `Dockerfile`、`docker-compose.yml`、`.dockerignore`、`requirements.txt`。
2. 写 `docker/supervisord.conf`。
3. 本地 `docker build`，解决构建错误（依赖、权限）。

### 第二阶段：Portal 适配（0.5 天）
1. 改 `process_manager.py`（Linux 进程终止 + Supervisor 模式）。
2. 改 `app.py`（webbrowser 条件化、升级路由禁用）。
3. 新增 `noop.sh`。
4. 本地验证 portal 首页可访问。

### 第三阶段：子应用适配（1 天）
1. `all_in_one` — tkinter DISPLAY 容错。
2. `domain_capture` — Linux Chromium 路径 + headless。
3. `test_report` — `stdin=DEVNULL`。
4. 逐个验证子应用通过 portal 代理可访问。

### 第四阶段：深度测试（0.5-1 天）
1. 配置生成全流程（选模板 → 填参 → 生成）。
2. 域名抓取全流程（输入 → Playwright 截图 → DNS 解析）。
3. 日志检查，无异常 traceback。

### 第五阶段：上云（0.5 天）
1. ECS 安装 Docker。
2. `git clone` / `scp` 代码到 ECS。
3. `docker compose up -d`。
4. 安全组开放 7000-7004。
5. 公网访问验证。

---

## 十、附录：命令速查

```bash
# 本地构建
docker build -t fivemins .

# 本地运行
docker compose up --build

# 后台运行
docker compose up -d

# 查看日志
docker compose logs -f

# 进入容器
docker exec -it fivemins-portal bash

# 重启服务
docker compose restart

# 升级（拉新代码 → 重建镜像 → 替换容器）
git pull
docker compose up -d --build

# 清理
docker compose down -v
```

---

**文档版本**：v1.0  
**编写日期**：2026-06-16  
**适用范围**：main 分支 → Linux Docker 部署
