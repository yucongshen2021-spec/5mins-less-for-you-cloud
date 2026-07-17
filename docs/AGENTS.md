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
| stats | 9000 | 统计看板 + 管理后台 + 用户个人数据看板 |

测试环境：8000→5000、8001→9000。其余子应用已停用。

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
cd application/test

# 黑箱测试
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/ -q           # 86 个

# 单元测试
python -m pytest all_in_one/test_apis.py test_generation.py -q

# 综合测试
cd all_in_one && python3 comprehensive.py                          # 185 个
```

## Git Push 网络问题

```bash
for ip in 140.82.112.3 140.82.113.3 140.82.114.3; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip OK" && echo "$ip github.com" | sudo tee -a /etc/hosts && break
done
git push origin main
```

## 部署到新服务器

```bash
git clone https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud.git
cd 5mins-less-for-you-cloud
docker compose up -d --build
curl http://localhost:5000/api/health  # {"ok":true,"status":"healthy"}
# 登录 yucs/yucs123，管理后台 9000/admin 密码 yucs123
```

环境变量：`SECRET_KEY`、`STATS_SECRET_KEY`、`ADMIN_PASSWORD`(yucs123)、`GUNICORN_WORKERS`(16，4G 内存建议 8)、`TZ`(Asia/Shanghai)。
