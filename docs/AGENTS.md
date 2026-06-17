# Agent 工作守则（先读，再动手）

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。
该文件只在本机维护，不进 git（`.gitignore` 已忽略），所以每台开发机看到的版本可能不同——以**本机当前版本**为准。

读完才允许动代码。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回 `config_error / network_error / incomparable`，前端文案禁止在异常时显示"已是最新"。任何"如果用户没传 X 就当成 Y"都要先问用户。
2. **没证据不宣称完成**。改 portal / proxy / 子应用链路后，必须启动 portal 并逐个验证子应用可加载、能交互，才能说"修好了"。
3. **新犯的错立刻补进 `log/mistake.txt`**，按已有格式（现象 / 根因 / 避免）追加。不允许只在聊天里说"下次注意"。

## 高频踩坑速查（详细版本在 log/mistake.txt）

- 端口：统一 5000 系列（portal `5000` + 4 个子应用 `5001-5004`）。改一处必全仓库 `rg`。
- 容器内由 supervisord 拉起 portal + 各子应用（见 `docker/supervisord.conf`）；`SUPERVISOR_MODE=1` 时 portal 只等待子应用端口、不自行 spawn。
- 验证 portal 模板内容用 `app.app.test_client()`，别真打 `curl /`（会被 sub-app 健康检查拖死）。
- 文件下载断言走 RFC 5987：`f"filename*=UTF-8''{quote(name)}" in disposition`。

## 测试铁律：禁止偷懒，必须从用户视角完整测试

**修改任何代码后，必须完整走完以下流程，否则不得声称"已修复"。API 返回 200 不等于功能正常。**

### 1. 全量自动化测试（必须全绿）

```bash
python -m pytest application/test/all_in_one/ -q
```

### 2. Portal 全应用冒烟（修改 portal / proxy / 子应用时必须手动 + Playwright）

启动 portal（裸机开发）：`cd application/portal && python app.py`
或容器内：`docker compose up -d` 后访问 `http://localhost:5000`

逐一验证：
- [ ] **配置生成** — 点击加载正常，无 502/代理错误
- [ ] **配置生成** — cascade menu 场景选择正常显示和交互
- [ ] **配置生成** — 生成配置功能正常
- [ ] **测试报告** — 点击加载正常，能正常生成报告（不报"读取不到模板"）
- [ ] **域名抓取** — 点击加载正常
- [ ] **配置梳理** — 点击加载正常，浏览器控制台无 JS 报错
- [ ] **配置梳理** — 粘贴配置 → 点击「解析并梳理」→ 正常解析出结果
- [ ] **配置梳理** — 控制台无 `Invalid regular expression flags` 等错误

**修改 proxy.py 后必须验证以上所有 4 个子应用。proxy 路径重写可能破坏任意一个子应用的 JS 正则。**

## 跑测试的标准命令

```bash
python -m pytest application/test/portal/test_update_check.py -q

cd application/test
python -m pytest --deselect all_in_one/test_e2e_playwright.py -q
```
