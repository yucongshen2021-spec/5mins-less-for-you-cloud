# 帮你节省5分钟 — ECS 配置生成工具

> 基于 Docker 的 Web 应用，通过浏览器粘贴数据头一键生成网络设备配置脚本。
> 支持 ER/USG/MPLS/AR 多厂商多场景，可视化模板编辑，多用户隔离，16 并发。

## 快速开始

```bash
git clone https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud.git
cd 5mins-less-for-you-cloud
docker compose up -d --build

# 配置生成: http://localhost:5000
# 统计后台: http://localhost:9000
```

管理员 `yucs` / `yucs123`（首次部署自动创建）。

## 服务架构

| 服务 | 端口 | 说明 |
|------|------|------|
| **Portal** | 5000 | 统一入口，反向代理，登录鉴权，分权后台入口 |
| **配置生成（all_in_one）** | 5003 | gunicorn 16 worker 多进程并发 |
| **stats 看板** | 9000 | 统计仪表盘 + 用户管理后台 + 用户个人数据看板 |

域名抓取（5001）、测试报告（5002）、配置梳理（5004）已停用（代码保留）。

## 登录与权限系统

- **自动访客模式**：未登录自动访客 session，**所有敏感功能禁用**（见下表）。
- **注册/登录/重置密码**：登录页三态切换，注册后自动登录，Session 30 天。
- **管理员 yucs**：首次部署自动创建（`ADMIN_PASSWORD`，默认 `yucs123`）。
- **工作区隔离**：每用户独立 `data/users/<uid>/editor_workspace/`，模板互不串号。
- **测试账号**：`test`/`ctest` 开头不记录访问日志。

### 访客 vs 登录用户权限对比

| 功能 | 访客（未登录） | 登录用户 | yucs 管理员 |
|------|--------------|---------|------------|
| 生成配置 | ❌ 按钮置灰 | ✅ | ✅ |
| 复制/导出/清除 | ❌ 按钮置灰 | ✅ | ✅ |
| 填写示例 | ❌ "登录后查看" | ✅ | ✅ |
| 备注说明 | ❌ "登录后查看" | ✅ | ✅ |
| 模板编辑器 | ❌ 只读+键盘拦截 | ✅ 可编辑 | ✅ 可编辑 |
| 初始化参数 | ❌ disabled | ✅ 可修改 | ✅ 可修改 |
| 9000 后台 | ❌ "请登录" | 🟢 我的数据 | 🟠 管理后台 |
| 用户管理 | — | — | ✅ 重置/删除用户 |

按钮在 **HTML 层面** disabled（Jinja2 条件渲染），不依赖 JS 执行。

### 分权后台（9000）

| 角色 | 5000 按钮 | 9000 页面 |
|------|----------|----------|
| yucs | 🟠 管理后台 | 全局统计 + 用户管理（重置密码/删除用户） |
| 普通用户 | 🟢 我的数据 | 个人生成记录 + 统计 + 常用场景 |
| 访客 | 🔘 后台（灰色） | "请登录后查看" → 跳转登录 |

后台只记录**生成配置**请求，其他操作不记录。所有时间统一北京时间 UTC+8。

管理后台（`/admin`）独立密码登录（`ADMIN_PASSWORD`），可列出/删除用户、重置密码，yucs 不可删。操作写入审计日志。

## 配置生成（5 工具 × 29 场景）

| 工具 | 变体 | 接口格式 |
|------|------|---------|
| ER FastIP 4.0 | HK/非香港/飞连/新增出口/域名分流 | eth{N} |
| ER FastIP 5.0 | HK/非香港/IPSec/飞连/新增出口/域名分流 | eth{N} |
| USG FastIP | HK/非香港/飞连/新增出口 | GE0/0/{N} |
| Epoch MPLS | 国内/海外/IPSec | eth{N} |
| AR SD-WAN | 单机/双机 × OPS/Factory | — |
| AR 传统组网 | 双线 | — |

### 参数同步

所有场景的 WAN/LAN 接口号、IP/CIDR、网关、内网段、DNS、DHCP、旁挂模式、回程路由等参数均同步到输出。HK 解析器支持 MAIN/BACKUP 和 LineID 两种数据头格式。US 出口的 overseas NAT block 支持 US 字段回退。所有场景的模板均通过 `_get_effective_template()` 从磁盘读取（支持用户自定义热更新）。

## 多并发架构

- **gunicorn 16 worker**：进程隔离，每 worker 独立 `_EMBEDDED_NS`。
- **tkinter_stub.py**：替代真实 tkinter，无需 Xvfb/DISPLAY。
- **generate 从磁盘读模板**（`_get_effective_template`），save/reset/load 只操作磁盘不改 ns。
- **`_load_init_defaults()`** 在所有 generate 路由调用，从 JSON 加载用户保存的参数。
- **`_FACTORY_INIT_DEFAULTS`** 在 import 时自动 snapshot（test_client 环境也有效）。
- **16 = 最大并发请求数**（不是用户数上限）。用户数走磁盘，每用户 ~10-50KB。

## 模板编辑器（我来定模板）

- 级联菜单 29 场景，可多选 chip 切换
- 数据头/变量映射/生成模板三个文本框
- 初始化默认参数（保存后影响 generate 输出）
- 保存自动加专属注释 `# xxx专属yyy场景模板-yymmdd`，重复保存不累积
- 预览不落盘，恢复 confirm 弹窗（iframe allow-modals）
- 热更新：save→generate 即时生效；用户间隔离

## 时间统一

所有时间统一北京时间（UTC+8）：
- 容器 `TZ=Asia/Shanghai`
- proxy.py `time.localtime()`
- auth DB `create_user()` 显式写 `datetime('now', '+8 hours')`
- `list_all_users()` / `get_user_by_id()` 读取时将老 UTC 数据加 8 小时转换
- stats DB 每日趋势 `DATE('now', '+8 hours')`

## 目录结构

```
5mins-less-for-you-cloud/
├── Dockerfile                          Debian + Python3 + tzdata + 中文字体
├── docker-compose.yml                  正式版（5000+9000）
├── docker-compose.test.yml             测试版（8000+8001）
├── docker/supervisord.conf             进程管理（portal + all_in_one + stats）
├── application/
│   ├── portal/                         Portal 入口 :5000
│   │   ├── app.py                      登录/注册/重置密码/session/自动访客
│   │   ├── proxy.py                    反向代理 + header 注入 + 日志记录
│   │   └── templates/
│   │       ├── index.html              首页（顶栏+侧栏+iframe）
│   │       └── login.html              登录页（三态切换）
│   ├── all_in_one - cc/                配置生成 :5003
│   │   ├── web/
│   │   │   ├── app.py                  Flask（generate+template+init-defaults API）
│   │   │   ├── gunicorn_conf.py        16 worker
│   │   │   ├── tkinter_stub.py         tkinter 替代
│   │   │   └── templates/index.html    前端 SPA（7 页签）
│   │   ├── src/                        业务模块源码（6 个生成器）
│   │   ├── data/                       运行时数据（per-user workspace）
│   │   └── editor_defaults/            出厂模板
│   ├── common/
│   │   ├── auth_db.py                  用户认证 DB（SQLite，created_at UTC+8 转换）
│   │   └── stats_db.py                 访问日志 DB（SQLite，per-user 查询）
│   ├── stats/                          统计看板 :9000
│   │   ├── app.py                      看板+管理后台+用户数据看板
│   │   └── templates/
│   │       ├── index.html              管理员看板
│   │       ├── user_dashboard.html     用户个人看板
│   │       ├── admin.html              用户管理后台
│   │       └── guest_login.html        访客登录提示
│   └── test/                           测试套件
│       ├── blackbox_8000/              黑箱测试（86 个）
│       └── all_in_one/                 单元测试 + comprehensive.py（185 个）
├── docs/
│   ├── AGENTS.md                      项目级工程守则（架构/运维/坑点，给 AI agent 看）
│   ├── GLOBAL_RULES.md                跨项目全局规则层（优先级低于 AGENTS.md）
│   ├── DESIGN.md                      UI 设计规范（以 all_in_one index.html :root 为真相来源）
│   └── 经历.md                        项目叙事与踩坑总结
├── log/                                变更日志（按日期）+ mistake.txt（跨日期踩坑记录）
└── test_features.md                    完整功能测试清单
```

## 测试

```bash
# 黑箱测试（需测试容器）
sudo docker compose -f docker-compose.test.yml up -d --build
sleep 12
cd application/test
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/ -q           # 86 个
python -m pytest all_in_one/test_apis.py test_generation.py -q     # 单元测试
cd all_in_one && python3 comprehensive.py                          # 185 个综合测试
```

## 部署到新服务器

```bash
git clone https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud.git
cd 5mins-less-for-you-cloud
docker compose up -d --build
curl http://localhost:5000/api/health  # {"ok":true,"status":"healthy"}
```

### 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `SECRET_KEY` | 随机 | Portal session 密钥 |
| `STATS_SECRET_KEY` | 同 SECRET_KEY | Stats session 密钥 |
| `ADMIN_PASSWORD` | yucs123 | 管理员密码 + stats 后台密码 |
| `GUNICORN_WORKERS` | 16 | gunicorn worker 数（4G 内存建议 8） |
| `TZ` | Asia/Shanghai | 容器时区 |
| `PORTAL_LABEL` | DEMO | 门户标签 |

## 开发须知

- **多并发安全**：generate 从磁盘读模板，save/reset/load 只操作磁盘不改 ns
- **访客权限**：HTML 层面 Jinja2 条件 disabled（24 个按钮），不依赖 JS。API 层面 `_require_login()` 拦截 examples/notes/template load/save/reset/preview/init-defaults
- **init-defaults**：`_load_init_defaults()` 在所有 generate 路由调用；save/reset 只写 JSON 不改 ns
- **tkinter 已移除**：用 `tkinter_stub.py`，不要恢复 `import tkinter` 或 Xvfb
- **时间统一 UTC+8**：容器 TZ，SQLite `+8 hours`，proxy `localtime()`，auth DB 老数据读取时转换
- **日志只记录生成请求**：proxy.py `is_generate` 过滤，test/ctest 用户不记录
- **模板热更新**：所有场景（含 AR SD-WAN、MPLS IPSec）均通过 `_get_effective_template` 读磁盘

## License

私有项目。未授权请勿外传。
