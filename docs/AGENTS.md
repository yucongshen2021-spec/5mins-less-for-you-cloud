# Agent 工作守则（先读，再动手）

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。
该文件只在本机维护，不进 git（`.gitignore` 已忽略），所以每台开发机看到的版本可能不同——以**本机当前版本**为准。

读完才允许动代码。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回 `config_error / network_error / incomparable`，前端文案禁止在异常时显示"已是最新"。任何"如果用户没传 X 就当成 Y"都要先问用户。
2. **没证据不宣称完成**。改 portal / proxy / 子应用链路后，必须启动 portal 并逐个验证子应用可加载、能交互，才能说"修好了"。
3. **新犯的错立刻补进 `log/mistake.txt`**，按已有格式（现象 / 根因 / 避免）追加。不允许只在聊天里说"下次注意"。

## 当前架构（2026-06-17 起）

- **tkinter 已移除**：业务模块用 `tkinter_stub.py` 替代。不要恢复 `import tkinter`、不要添加 Xvfb / DISPLAY 依赖。
- **gunicorn 8 worker**：all_in_one 用 gunicorn 多 worker 进程隔离并发。每 worker 独立 `_EMBEDDED_NS`，worker 间天然并发。
- **实际启动服务**：portal(:5000) + all_in_one(:5003, gunicorn) + stats(:9000)。其余子应用（域名抓取/测试报告/配置梳理）已停用，代码保留。
- **多用户并发安全**：generate 从磁盘读模板（`_get_effective_template`），save/reset 只操作磁盘不改 ns。不要在 save/reset 里调 `_apply_template_to_runtime` 或 `del _EMBEDDED_NS`。

## 高频踩坑速查（详细版本在 log/mistake.txt）

- 端口：portal `5000`，all_in_one `5003`，stats `9000`。测试环境 `8000→5000`、`8001→9000`。
- 容器内由 supervisord 拉起 portal + all_in_one(gunicorn) + stats（见 `docker/supervisord.conf`）；`SUPERVISOR_MODE=1` 时 portal 只等待子应用端口、不自行 spawn。
- 验证 portal 模板内容用 `app.app.test_client()`，别真打 `curl /`（会被 sub-app 健康检查拖死）。
- **不要 `del _EMBEDDED_NS`**：删缓存会导致并发 generate 崩溃。用 `_FACTORY_INIT_DEFAULTS` 快照恢复 globals。
- **save 原子写入**：先写唯一临时文件再 `replace`，避免并发冲突。
- 业务模块源码里的 `import tkinter` / `from tkinter import` 会被 `_load_module` 预处理注释掉，stub 已在 ns 中提供。

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
python -m pytest blackbox_8000/ -q -k "not template_lifecycle"
```

预期：**54+ passed / 0 failed**

### 3. 并发验证（8 worker 无串号）

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
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as p:
    print('✅ 全通过' if all(p.map(req,range(1,9))) else '❌ 有失败')
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
python -m pytest blackbox_8000/ -q -k "not template_lifecycle"
```
