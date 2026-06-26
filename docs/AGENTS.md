# Agent 工作守则（先读，再动手）

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。
该文件只在本机维护，不进 git（`.gitignore` 已忽略），以**本机当前版本**为准。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回错误，前端禁止在异常时显示"已是最新"。
2. **没证据不宣称完成**。改 portal / proxy / 子应用链路后，必须启动并逐个验证。
3. **新犯的错立刻补进 `log/mistake.txt`**。

## 当前架构（2026-06-26 起）

### 核心服务

| 服务 | 端口 | 说明 |
|------|------|------|
| Portal | 5000 | 统一入口，反向代理，登录鉴权，分权后台入口 |
| all_in_one | 5003 | gunicorn 16 worker，配置生成 |
| stats | 9000 | 统计看板 + 管理后台 + 用户个人数据看板 |

测试环境：8000→5000、8001→9000。其余子应用已停用。

### 技术栈

- **tkinter 已移除**：用 `tkinter_stub.py` 替代。不要恢复 `import tkinter`、不要添加 Xvfb / DISPLAY。
- **gunicorn 16 worker**：进程隔离，每 worker 独立 `_EMBEDDED_NS`。16 = 最大并发请求数，不是用户数上限。
- **时间统一 UTC+8**：容器 `TZ=Asia/Shanghai`，SQLite 用 `datetime('now','+8 hours')`，proxy 用 `time.localtime()`。

### 登录与权限

- **注册/登录/重置密码**：登录页三态切换，注册后自动登录，Session 30 天。
- **管理员 yucs**：`init_auth_db()` 自动创建，密码 `ADMIN_PASSWORD`（默认 `yucs123`）。
- **访客**：自动 session（user_id="" → 共享 workspace），模板只读。
- **模板编辑权限**：登录用户可编辑（`_require_login()` 检查 X-User-Id 非空）。访客只读+键盘拦截。
- **模板专属注释**：保存自动加 `# xxx专属yyy场景模板-yymmdd`，重复保存不累积。
- **工作区隔离**：`_get_user_data_dir()` 按 X-User-Id 路由到 `data/users/<uid>/`。
- **测试账号**：`test`/`ctest` 开头不记录日志（proxy.py `startswith(("test","ctest"))` 大小写不敏感）。

### 分权后台（9000）

| 角色 | 5000 按钮 | 9000 页面 |
|------|----------|----------|
| yucs | 🟠 管理后台 | 全局统计 + 用户管理（`/admin`，密码 `ADMIN_PASSWORD`） |
| 普通用户 | 🟢 我的数据 | 个人生成记录（`user_dashboard.html`） |
| 访客 | 🔘 后台 | "请登录后查看"（`guest_login.html`） |

- 管理后台独立 session（stats `secret_key`），可列出/删除用户、重置密码，yucs 不可删，操作写审计日志。
- **只记录生成配置请求**：proxy.py `is_generate` 过滤，非生成操作不记录。
- 返回按钮：用户看板→5000，管理后台→9000看板+5000首页。

### 参数同步（generate 路由）

- `_load_init_defaults()` 在所有 5 个 generate 路由调用，保存的初始化参数影响输出。
- `_patch_format_dict(ns=...)` 用 ns 中的 init-defaults 作为 lan_cidr 回退。
- HK 解析器支持 MAIN/BACKUP 和 LineID 两种数据头格式（LineID 奇偶数区分主备线）。
- US 出口 overseas NAT block 支持 US 字段回退（main_us_tun/bk_us_tun/main_us_nat_ip）。
- MPLS inner_nets 覆盖后重新生成 prefix_list_block。

## 高频踩坑速查

- **不要 `del _EMBEDDED_NS`**：删缓存导致并发 generate 崩溃。
- **save 原子写入**：先写唯一临时文件再 `replace`。
- **ns 污染**：`api_template_reset` 把读到的模板写回 ns。脏 ns 必须 SIGHUP 重启 worker。busybox 容器用 `bash -c 'kill -HUP <master_pid>'`。
- **_FACTORY_INIT_DEFAULTS lookup**：reset 路由用 `scenario_key`（不是 `source` 文件名）查找。
- **iframe sandbox**：需 `allow-modals` 才能 `confirm()` 弹窗。
- **favicon**：portal + all_in_one 各有 `/favicon.ico` 路由返回 204。
- **业务模块 `import tkinter`**：被 `_load_module` 预处理注释掉，stub 已在 ns 中。

## 跑测试的标准命令

```bash
# 测试容器
sudo docker-compose -f docker-compose.test.yml up -d --build
sleep 12

# 黑箱测试（58 API + 28 多用户并发 = 86）
cd application/test
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/ -q

# 单元测试
python -m pytest all_in_one/test_apis.py all_in_one/test_generation.py -q

# 并发验证（16 worker 无串号）
python3 -c "
import urllib.request, json, concurrent.futures
BASE='http://localhost:8000/app/all_in_one'
HDR='hostname:TEST\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.55.14.64/30\n'
def req(i):
    p=json.dumps({'variant':'hk','header_text':HDR,'network':{'wan_cidr':f'10.{i}.{i}.{i}/24','lan_cidr':f'192.168.{i}.1/24'}}).encode()
    r=urllib.request.Request(f'{BASE}/api/generate/epoch_fastip',data=p,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r,timeout=30) as r: d=json.loads(r.read()); o=d.get('output','')
    return f'10.{i}.{i}.{i}' in o and len(o)>1000
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as p:
    print('✅ 全通过' if all(p.map(req,range(1,17))) else '❌ 有失败')
"
```

## Git Push 网络问题（GitHub 443 不通）

国内云服务器 `github.com` 默认 443 端口不通。解决方案：

```bash
# 测试可达 IP
for ip in 140.82.112.3 140.82.113.3 140.82.114.3; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip OK" || echo "$ip FAIL"
done

# 添加到 /etc/hosts
echo "140.82.112.3 github.com" | sudo tee -a /etc/hosts

# Push
git push origin main
```

如果该 IP 也不通，重新测试换一个。GitHub IP 列表见 https://api.github.com/meta 的 `web` 字段。

## 部署到新服务器

```bash
git clone https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud.git
cd 5mins-less-for-you-cloud
docker compose up -d --build
curl http://localhost:5000/api/health  # {"ok":true,"status":"healthy"}
# 登录 yucs/yucs123，管理后台 9000/admin 密码 yucs123
```

环境变量：`SECRET_KEY`、`STATS_SECRET_KEY`、`ADMIN_PASSWORD`(yucs123)、`GUNICORN_WORKERS`(16)、`TZ`(Asia/Shanghai)。
