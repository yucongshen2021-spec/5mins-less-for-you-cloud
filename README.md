# 帮你节省 5 分钟 · 网络配置工具套件（Demo 版）

一组本地工具，把日常重复的网络运维工作从「敲 5 分钟」压成「点 1 下」。

[![tests](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml/badge.svg)](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml)

---

## 版本说明

项目为 **纯 Demo 版本**，端口统一使用 5000 系列。不再区分 Demo/Release 双版本。

当前实际启动的服务（supervisord 管理）：

| 服务 | 端口 | 说明 |
|------|------|------|
| **Portal** | 5000 | 统一入口，反向代理，登录鉴权，状态监控 |
| **配置生成（all_in_one）** | 5003 | gunicorn 16 worker 多进程并发 |
| **stats 访问看板** | 9000 | 访问日志统计仪表盘（含用户搜索）+ 管理后台（`/admin`） |

域名抓取（5001）、测试报告（5002）、配置梳理（5004）当前已停用（代码保留，supervisord 注释），恢复时取消 `docker/supervisord.conf` 对应段注释即可。

### 登录系统

- **自动访客模式**：未登录自动获得访客 session，使用共享默认 workspace。
- **注册/登录/重置密码**：登录页支持三态切换（登录 ↔ 注册 ↔ 重置密码）。重置密码需输入用户名 + 旧密码 + 新密码。
- **管理员 yucs**：首次部署时自动创建 `yucs` 账号（密码从 `ADMIN_PASSWORD` 环境变量读取，默认 `yucs123`）。
- **模板编辑权限**：登录用户可编辑自己的模板（访客不可编辑）。保存时自动加专属注释 `xxx专属yyy场景模板-yymmdd`。yucs 是管理员。
- **按用户工作区隔离**：每个用户有独立的 `data/users/<uid>/editor_workspace/`，模板互不串号。
- **会话有效期**：24 小时（Flask permanent session）。

---

## 核心应用：配置生成（all_in_one）

Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN / AR 传统组网 一键生成；可视化模板编辑器。

**多并发架构**：gunicorn 16 worker 进程隔离，每个 worker 独立加载业务模块，worker 间天然并发。tkinter 已被 `tkinter_stub.py` 完全替代，**无需 Xvfb / DISPLAY**，无线程安全约束。

打开 portal 统一入口即可访问全部子应用。点击右上角 **"?"** 查看使用教程。

---

## 启动

```bash
docker compose up -d        # 一键启动，打开 http://localhost:5000
```

停止：`docker compose down`。容器内由 supervisord 统一拉起 portal + all_in_one（gunicorn）+ stats，停止容器即全部清理。

### 测试环境（8000 端口）

所有改动先在 8000 端口测试，通过后再重建正式 5000 容器：

```bash
sudo docker-compose -f docker-compose.test.yml up -d --build   # 构建+启动
# 访问 http://localhost:8000（Portal）、http://localhost:8001（stats）
sudo docker-compose -f docker-compose.test.yml down            # 停止
```

---

## 运行环境

- **部署环境**：Linux 云服务器（4C4G）+ Docker Compose 单容器部署，Python 3.11
  ```bash
  docker build -t fivemins .
  docker compose up -d
  ```
- **裸机开发**：Linux / Windows 10/11，Python 3.11+
  ```bash
  pip install -r requirements.txt
  # 无需 tkinter / Xvfb / DISPLAY（已用 tkinter_stub 替代）
  playwright install chromium          # 仅 domain_capture + E2E 测试需要
  ```

---

## 目录结构

```
.
├── application/
│   ├── portal/                      统一入口 + 反向代理 :5000
│   ├── all_in_one - cc/             配置生成 :5003（gunicorn 16 worker）
│   │   ├── web/
│   │   │   ├── app.py               Flask 后端
│   │   │   ├── wsgi.py              gunicorn 入口
│   │   │   ├── gunicorn_conf.py     gunicorn 配置（8 worker）
│   │   │   └── tkinter_stub.py      tkinter 替代模块（纯 Python mock）
│   │   ├── src/                     业务模块（6 个厂商配置生成器）
│   │   └── data/                    模板数据 + 用户配置
│   ├── stats/                       访问日志看板 :9000
│   ├── 自动做测试报告 - cc/          测试报告（停用）
│   ├── 自动抓域名发2/                域名抓取（停用）
│   ├── 自动梳理配置 - cc/            配置梳理（停用）
│   ├── common/                      共享模块（stats_db）
│   └── test/                        全部测试（含 blackbox_8000 黑箱）
├── docker/
│   └── supervisord.conf             进程编排（portal + all_in_one + stats）
├── docker-compose.yml               正式编排（5000 + 9000）
├── docker-compose.test.yml          测试编排（8000→5000, 8001→9000）
├── Dockerfile
├── .github/workflows/test.yml       CI 测试（main 分支）
├── log/                             变动记录
├── plan/                            设计文档
└── README.md
```

---

## 测试

### 全量后端测试（test_client，无需容器）

```bash
cd application/test
python -m pytest --deselect all_in_one/test_e2e_playwright.py
```

预期：**170+ passed**（无 tkinter / 无 DISPLAY / 无 Xvfb）

### 8000 端口黑箱测试（需启动测试容器）

```bash
cd application/test
python -m pytest blackbox_8000/ -q
```

### 多用户并发测试（16 用户 + 工作区隔离 + 权限控制）

```bash
cd application/test
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/test_multiuser_concurrency.py -v
```

覆盖：16 用户登录、session 隔离、工作区目录独立、模板不串号、16 并发生成无 5xx、yucs 权限控制。

### 并发验证（16 worker，无串号）

```bash
# 启动测试容器后，并发发 8 个不同参数的 generate 请求
python -c "
import urllib.request, json, concurrent.futures
# ... 见 log/2026-06-17.md 中的测试脚本
"
```

### Playwright 浏览器 E2E

```bash
cd application/test/all_in_one
python test_e2e_playwright.py --quick
```

```bash
pip install pytest-playwright psutil
playwright install chromium
```

---

## 开发须知

- **永远不要用兜底逻辑**：输出必须可重现，不允许猜测
- **TDD**：先写测试，再写实现
- **每次有动作记一笔**：`log/` 目录存变动记录
- **多并发安全**：generate 从磁盘读模板（`_get_effective_template`），save/reset 只操作磁盘不改 ns，避免并发竞态
- **模板编辑器权限**：登录用户可编辑自己的模板（访客不可编辑），保存时自动加专属注释。yucs 是管理员
- **登录系统**：注册/登录/重置密码（旧密码验证）。首次部署自动创建 yucs 管理员。访客自动 session 用共享 workspace
- **stats 用户搜索**：9000 看板支持按用户名模糊搜索，表格含用户列，Top 用户图表
- **tkinter 已移除**：业务模块用 `tkinter_stub.py` 替代，不要恢复 `import tkinter` 或添加 Xvfb 依赖

---

## License

私有项目。未授权请勿外传。


---

## 管理后台（9000 端口 `/admin`）

访问 `http://localhost:9000/admin`（测试环境 `http://localhost:8001/admin`），输入管理密码登录（`ADMIN_PASSWORD` 环境变量，默认 `yucs123`）。

功能：
- **用户列表**：查看所有注册用户（用户名、创建时间）
- **重置密码**：管理员重置任意用户密码（不需旧密码）
- **删除用户**：删除用户（yucs 管理员不可删除）

管理后台使用独立 session（stats app 的 `secret_key`），与 portal 登录系统互不依赖。
