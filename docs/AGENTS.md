# Agent 工作守则（先读，再动手）

## ⛔ 删除/清理操作铁律（2026-07-13 血泪教训）

**任何 `rm`、`delete`、`kill`、`DROP`、`TRUNCATE`、清理数据等不可逆操作：**

1. **先在 8000 端口模拟执行**，确认影响范围（8000→5000 映射测试环境）
2. **展示将要删除的内容清单**，等待用户确认
3. **再次确认**后才能在正式环境（5000）执行
4. **禁止**使用 `*` 通配符批量删除，必须精准匹配目标
5. 涉及用户数据时，**先 `find`/`ls` 列出所有目标**，确认只包含 yuc/访客，不包含其他正常用户

> **2026-07-13 事故**：用户要求"删掉 yuc 和访客的生成数据记录"，Agent 直接 `rm -rf *` 清空了所有容器的 `user_activity/` 和 `users/` 目录，导致生产环境其他正常用户的模板、配置全部丢失，无法恢复。

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。以**本机当前版本**为准。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回错误。
2. **没证据不宣称完成**。改代码后必须启动并验证。
3. **新犯的错立刻补进 `log/mistake.txt`**。

## 核心服务

| 服务 | 端口 | 说明 |
|------|------|------|
| Portal | 5000 | 统一入口，反向代理，登录鉴权，分权后台入口 |
| all_in_one | 5003 | gunicorn 16 worker，配置生成 |
| usg_virus_test | 5005 | USG 测病毒操作指引页（说明+域名清单+一键下载 ZIP），纯展示 |
| fastip_report | 5006 | FASTIP 测试报告指引页 + 桌面版（Windows exe）下载 |
| stats | 9000 | 统计看板 + 管理后台 + 用户个人数据看板 |
| port80-test | 80 | 连通性测试页（独立容器，与业务完全隔离） |

测试环境：8000→5000、8001→9000。其余子应用（域名抓取/测试报告/配置梳理）已停用。
前端状态：ER FastIP 5.0 变体入口与 AR SD-WAN 页签已禁用（显示「测试中」）。

## 技术栈

- **tkinter 已移除**：用 `tkinter_stub.py` 替代。不要恢复 `import tkinter`、不要添加 Xvfb/DISPLAY。
- **gunicorn 16 worker**：进程隔离，每 worker 独立 `_EMBEDDED_NS`。16 = 最大并发请求数。
- **时间统一 UTC+8**：容器 `TZ=Asia/Shanghai`，SQLite 用 `datetime('now','+8 hours')`，proxy 用 `time.localtime()`，auth DB 老数据读取时加 8 小时转换。

## 登录与权限

- **注册/登录/重置密码**：登录页三态切换，注册后自动登录，Session 30 天。
- **管理员 yucs**：`init_auth_db()` 自动创建，密码 `ADMIN_PASSWORD`（默认 `yucs123`）。
- **访客**：自动 session（user_id="" → 共享 workspace），**所有敏感功能禁用**。

### 访客禁用清单（HTML 层面 Jinja2 disabled，不依赖 JS）

| 功能 | 访客 |
|------|------|
| 生成配置/复制/导出/清除 | ❌ 按钮置灰 |
| 填写示例 (`/api/examples`) | ❌ 403 + "登录后查看填写示例" |
| 备注说明 (`/api/notes`) | ❌ 403 + "登录后查看备注说明" |
| 模板编辑器（选择场景/保存/预览/恢复） | ❌ 按钮置灰 + textarea readonly + 键盘拦截 |
| 初始化参数 | ❌ 所有 input disabled |
| 9000 后台 | ❌ "请登录后查看" |

共 24 个按钮在 HTML 层面 disabled。API 层面 `_require_login()` 拦截所有敏感接口。

### 模板编辑权限

- 登录用户可编辑自己的模板（`_require_login()` 检查 X-User-Id 非空）。
- 保存自动加 `# xxx专属yyy场景模板-yymmdd`，重复保存不累积。
- 工作区隔离：`_get_user_data_dir()` 按 X-User-Id 路由到 `data/users/<uid>/`。
- 测试账号：`test`/`ctest` 开头不记录日志。

### 分权后台（9000）

| 角色 | 5000 按钮 | 9000 页面 |
|------|----------|----------|
| yucs | 🟠 管理后台 | 全局统计 + 用户管理（`/admin`，密码 `ADMIN_PASSWORD`） |
| 普通用户 | 🟢 我的数据 | 个人生成记录（`user_dashboard.html`） |
| 访客 | 🔘 后台 | "请登录后查看"（`guest_login.html`） |

- 管理后台独立 session，可列出/删除用户、重置密码，yucs 不可删，操作写审计日志。
- **只记录生成配置请求**：proxy.py `is_generate` 过滤。
- 返回按钮：用户看板→5000，管理后台→9000看板+5000首页。

## 参数同步（generate 路由）

- `_load_init_defaults()` 在所有 5 个 generate 路由调用，从 JSON 加载用户保存的参数。
- `_patch_format_dict(ns=...)` 用 ns 中的 init-defaults 作为 lan_cidr 回退。
- HK 解析器支持 MAIN/BACKUP 和 LineID 两种数据头格式（LineID 奇偶数区分主备线）。
- US 出口 overseas NAT block 支持 US 字段回退（main_us_tun/bk_us_tun/main_us_nat_ip）。
- MPLS inner_nets 覆盖后重新生成 prefix_list_block。
- **所有场景（含 AR SD-WAN、MPLS IPSec）均通过 `_get_effective_template` 读磁盘模板**，支持自定义热更新。

## 高频踩坑速查

- **不要 `del _EMBEDDED_NS`**：删缓存导致并发 generate 崩溃。
- **save 原子写入**：先写唯一临时文件再 `replace`。
- **ns 污染**：`api_template_reset` 不再写 ns（Bug 3 修复）。`api_template_load` 也不写 ns（Bug 2 修复）。`api_init_defaults_save/reset` 也不写 ns。只有 `_load_init_defaults()` 在 generate 时从 JSON 加载到 ns。
- **`_FACTORY_INIT_DEFAULTS` lookup**：用 `scenario_key`（不是 `source` 文件名）。import 时自动 snapshot。
- **iframe sandbox**：需 `allow-modals` 才能 `confirm()` 弹窗。
- **favicon**：portal + all_in_one 各有 `/favicon.ico` 路由返回 204。
- **访客按钮 disabled**：在 HTML 层面用 `{% if not template_editable %}disabled{% endif %}`，不依赖 JS。
- **auth DB created_at**：老数据是 UTC，`list_all_users()` / `get_user_by_id()` 读取时加 8 小时。新数据用 `datetime('now', '+8 hours')` 显式写入。
- **test-user 数据**：`data/users/test*` 在 .gitignore 中，不要 `git add`。

## 跑测试的标准命令

```bash
sudo docker-compose -f docker-compose.test.yml up -d --build
sleep 12

# 黑箱测试（从 application/test 运行；需 8000 容器，容器不在时自动跳过）
cd application/test
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/ -q           # 86 个（含 28 项多用户并发）

# 单元/回归（从仓库根运行；pytest.ini 的忽略路径按仓库根解析）
cd ../..
python -m pytest application/test/all_in_one -q                    # 147 个（浏览器用例自动跳过）

# 综合测试（容器内 in-process；镜像不含 test 目录，需先 docker cp 进去）
sudo docker cp "/opt/fivemins/application/test" fivemins-portal-test:/app/application/test
sudo docker exec fivemins-portal-test sh -c 'cd "/app/application/test/all_in_one" && python3 comprehensive.py'   # 280 个
```

## 端到端测试定义（项目级细化全局 Rule 8）

全局规则（`docs/GLOBAL_RULES.md` Rule 8）默认要求 UI 项目用 Playwright。**本项目按优先级做如下细化，优先于全局 Rule 8**：

本项目的"端到端真实测试"= 以下三件齐备，不强制引入 Playwright：

1. **pytest 黑箱全绿**：`blackbox_8000/`（覆盖 5000 入口真实 HTTP 路径）
2. **comprehensive 全绿**：`all_in_one/comprehensive.py`（全场景生成回归）
3. **浏览器手动冒烟**（mistake #52 铁律）：启动 portal -> 选场景 -> 粘贴标准数据头 -> 点生成 -> 肉眼检查输出与标准脚本一致；并检查「我来定模板」级联下拉可见/可加载/可预览。**禁止只 `curl /api/generate/...` 就宣称完成。**

Playwright 仅在需要回归一段固定交互序列（如级联下拉、模板编辑器生命周期）且手动冒烟成本过高时才引入，引入前需在 `plan/` 落方案。

## Git Push 网络问题

```bash
# GitHub IP 会漂移（2026-10-12 实测可用：20.205.243.166，已写入 /etc/hosts）。失效时重新探测：
for ip in 20.205.243.166 140.82.114.3 140.82.114.4 20.27.177.113 140.82.112.3; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip OK" \
    && sudo sed -i '/github.com/d' /etc/hosts \
    && echo "$ip github.com" | sudo tee -a /etc/hosts && break
done
# 候选 IP 来源：curl -s "https://dns.alidns.com/resolve?name=github.com&type=A"
git push origin main
```

## 部署到新服务器

```bash
git clone https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud.git
cd 5mins-less-for-you-cloud
docker-compose up -d --build   # 本机为 Compose v2 独立二进制；插件形式环境等价 docker compose
curl http://localhost:5000/api/health  # {"ok":true,"status":"healthy"}
# 登录 yucs/yucs123，管理后台 9000/admin 密码 yucs123
```

环境变量：`SECRET_KEY`、`STATS_SECRET_KEY`、`ADMIN_PASSWORD`(yucs123)、`GUNICORN_WORKERS`(16，4G 内存建议 8)、`TZ`(Asia/Shanghai)。
