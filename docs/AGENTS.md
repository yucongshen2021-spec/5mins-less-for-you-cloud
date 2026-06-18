# Agent 工作守则（先读，再动手）

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。
该文件只在本机维护，不进 git（`.gitignore` 已忽略），所以每台开发机看到的版本可能不同——以**本机当前版本**为准。

读完才允许动代码。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回 `config_error / network_error / incomparable`，前端文案禁止在异常时显示"已是最新"。任何"如果用户没传 X 就当成 Y"都要先问用户。
2. **没证据不宣称完成**。改 portal / proxy / 子应用链路后，必须启动 portal 并逐个验证子应用可加载、能交互，才能说"修好了"。
3. **新犯的错立刻补进 `log/mistake.txt`**，按已有格式（现象 / 根因 / 避免）追加。不允许只在聊天里说"下次注意"。

## 当前架构（2026-06-18 起）

- **tkinter 已移除**：业务模块用 `tkinter_stub.py` 替代。不要恢复 `import tkinter`、不要添加 Xvfb / DISPLAY 依赖。
- **gunicorn 16 worker**：all_in_one 用 gunicorn 多 worker 进程隔离并发。每 worker 独立 `_EMBEDDED_NS`，worker 间天然并发。4C4G 可支持 16 worker。
- **实际启动服务**：portal(:5000) + all_in_one(:5003, gunicorn 16w) + stats(:9000)。其余子应用（域名抓取/测试报告/配置梳理）已停用，代码保留。
- **多用户并发安全**：generate 从磁盘读模板（`_get_effective_template`），save/reset 只操作磁盘不改 ns。不要在 save/reset 里调 `_apply_template_to_runtime` 或 `del _EMBEDDED_NS`。
- **登录系统**：注册/登录/重置密码（旧密码验证）。首次部署 `init_auth_db()` 自动创建 yucs 管理员（密码 `ADMIN_PASSWORD` 环境变量，默认 `yucs123`）。访客自动 session（user_id="" → 共享 workspace）。
- **模板编辑器权限**：登录用户可编辑自己的模板，访客（未登录）不可编辑。后端 `_require_login()` 检查 `X-User-Id` 非空，访客返回 403。前端 `TEMPLATE_EDITABLE` 置灰按钮 + 只读提示横幅。`yucs` 是管理员（`IS_ADMIN`）。
- **模板专属注释**：保存模板时自动在 `.tpl` 顶部加注释行 `# xxx专属yyy场景模板-yymmdd`（xxx=用户名，yyy=场景名，yymmdd=日期）。重复保存自动更新注释，不累积。
- **并发 vs 用户数**：16 = gunicorn worker 数 = 最大同时并发请求数，不是用户数上限。用户数和 workspace 走磁盘（每用户约 10-50KB），与内存无关。16 worker ≈ 2.6GB 内存。
- **按用户工作区隔离**：`_get_user_data_dir()` 按 `X-User-Id` header 路由到 `data/users/<uid>/`，proxy 防伪造（剥离客户端 X-User-Id）。
- **管理后台**：9000 端口 `/admin` 路径，独立密码登录（`ADMIN_PASSWORD` 环境变量，默认 `yucs123`）。可列出/删除用户、重置用户密码。yucs 不可删除。stats app 设置了 `secret_key` 和 `session`。

## 高频踩坑速查（详细版本在 log/mistake.txt）

- 端口：portal `5000`，all_in_one `5003`，stats `9000`。测试环境 `8000→5000`、`8001→9000`。
- 容器内由 supervisord 拉起 portal + all_in_one(gunicorn) + stats（见 `docker/supervisord.conf`）；`SUPERVISOR_MODE=1` 时 portal 只等待子应用端口、不自行 spawn。
- 验证 portal 模板内容用 `app.app.test_client()`，别真打 `curl /`（会被 sub-app 健康检查拖死）。
- **不要 `del _EMBEDDED_NS`**：删缓存会导致并发 generate 崩溃。用 `_FACTORY_INIT_DEFAULTS` 快照恢复 globals。
- **save 原子写入**：先写唯一临时文件再 `replace`，避免并发冲突。
- **ns 污染无法 reset 清除**：`api_template_reset` 会把读到的模板写回 ns（`ns[slot] = tpl`）。如果 ns 被脏模板污染，reset 只会写回脏值。必须 SIGHUP 重启 gunicorn worker 才能恢复出厂 ns。busybox 容器无独立 `kill` 命令，用 `bash -c 'kill -HUP <master_pid>'`。
- **业务模块源码里的 `import tkinter` / `from tkinter import` 会被 `_load_module` 预处理注释掉，stub 已在 ns 中提供。

## 测试铁律：禁止偷懒，必须从用户视角完整测试

**修改任何代码后，必须完整走完以下流程，否则不得声称"已修复"。API 返回 200 不等于功能正常。**

### 1. 全量 test_client 测试（无需容器、无需 DISPLAY）

```bash
cd application/test
python -m pytest --ignore=blackbox_8000 --ignore=domain_capture \
  --deselect all_in_one/test_e2e_playwright.py -q
```

预期：**170+ passed / 0 failed**

### 2. 8000 端口黑箱测试（需启动测试容器）

```bash
sudo docker-compose -f docker-compose.test.yml up -d --build
sleep 12
cd application/test
python -m pytest blackbox_8000/test_full_api.py -q
```

预期：**58 passed / 0 failed**

### 3. 多用户并发测试（16 用户 + 工作区隔离 + 权限控制）

```bash
cd application/test
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/test_multiuser_concurrency.py -v
```

预期：**20 passed / 0 failed**

覆盖：16 用户登录、session 隔离、工作区目录独立、模板不串号、16 并发生成无 5xx、yucs 权限控制（403）。
注意：该测试会 SIGHUP 重启 gunicorn worker 清除脏 ns，耗时约 18s。

### 4. 并发验证（16 worker 无串号）

```bash
# 并发发 8 个不同参数的 generate 请求，检查无串号
python3 -c "
import urllib.request, json, concurrent.futures
BASE='http://localhost:8000/app/all_in_one'
HDR='hostname:TEST\nLineID:609157A1\nPE:szd-ape2\ntunnel:vtun1213\nwanip:10.55.14.64/30\ninner:192.168.10.0/24\n'
def req(i):
    p=json.dumps({'variant':'hk','header_text':HDR,'network':{'wan_cidr':f'10.{i}.{i}.{i}/24','lan_cidr':f'192.168.{i}.1/24','wan_gw':f'10.{i}.{i}.{i}.254'}}).encode()
    r=urllib.request.Request(f'{BASE}/api/generate/epoch_fastip',data=p,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(r,timeout=30) as r: d=json.loads(r.read()); o=d.get('output','')
    return f'10.{i}.{i}.{i}' in o and f'192.168.{i}.1/24' in o and len(o)>1000
with concurrent.futures.ThreadPoolExecutor(max_workers=16) as p:
    print('✅ 全通过' if all(p.map(req,range(1,17))) else '❌ 有失败')
"
```

### 4. Portal 冒烟（修改 portal/proxy 时）

启动测试容器后访问 `http://localhost:8000`：
- [ ] **配置生成** — 点击加载正常，无 502/代理错误
- [ ] **配置生成** — 生成配置功能正常（含多场景）
- [ ] **stats 看板** — 访问 `http://localhost:8001` 正常显示

**修改 proxy.py 后必须验证配置生成 + stats 看板。**

## 跑测试的标准命令

```bash
# test_client（裸机，无需容器）
cd application/test
python -m pytest --ignore=blackbox_8000 --ignore=domain_capture \
  --deselect all_in_one/test_e2e_playwright.py -q

# 8000 黑箱（需测试容器）
python -m pytest blackbox_8000/test_full_api.py -q

# 多用户并发（需测试容器，16 用户）
YUCS_PASSWORD=yucs123 python -m pytest blackbox_8000/test_multiuser_concurrency.py -v
```

## Git Push 网络问题（GitHub 443 端口不通）

国内云服务器 `github.com` 默认解析到 `20.205.243.166`，其 443 端口经常不通（ICMP 通但 TCP 443 超时）。
SSH 22 端口可通但需配 SSH key。

**解决方案**：在 `/etc/hosts` 中将 `github.com` 指向 443 可达的 GitHub IP：

```bash
# 测试哪些 GitHub IP 的 443 端口可达
for ip in 140.82.112.3 140.82.113.3 140.82.114.3; do
  timeout 5 bash -c "echo > /dev/tcp/$ip/443" 2>/dev/null && echo "$ip:443 OK" || echo "$ip:443 FAIL"
done

# 添加到 /etc/hosts（选一个 OK 的 IP）
echo "140.82.112.3 github.com" | sudo tee -a /etc/hosts

# 验证 HTTPS 可达
curl -sI https://github.com | head -1   # 应返回 HTTP/2 200

# 然后 push
git push origin main
```

注意：如果该 IP 后续也不通，重新测试并换一个可达的 IP。GitHub IP 列表见 https://api.github.com/meta 的 `web` 字段。
