# 帮你节省5分钟 — 项目规则

## 版本架构（最高优先级）

项目有 **两个版本**，严格分离，不可混淆：

### Demo 版（开发/试用）
- **端口**: 5000（portal）+ 5001-5004（子应用）
- **启动**: 源码直接运行 `py application/portal/app.py`
- **RELEASE_MODE**: 不设置
- **页面**: DEMO 橙色标签、"demo试用版"
- **侧栏底部**: **下载卡片** (dlCard) — 扫描 dist/ 最新 zip，显示版本号和大小
- **更新检查**: **不做**（无横幅、无检查按钮、无自动定时器）
- **RELEASE_INFO.json**: 读项目根目录的文件
- **/api/download/latest**: 扫描 dist/ 返回最新 zip 元数据

### Release 版（客户交付）
- **端口**: 7000（portal）+ 7001-7004（子应用）
- **启动**: 解压 zip → 双击 `start_all.bat`
- **端口**: app.py 硬编码 7000，process_manager 硬编码 7001-7004。不依赖环境变量。
- **页面**: RELEASE 绿色标签、"正式版"、手动检查版本按钮
- **侧栏底部**: **更新卡片** (upgradeBtn) — 5 态按钮（检查中/已是最新/有新版本/错误/升级中）
- **更新检查**: **必须做**（5 秒自动 + 手动按钮 + 横幅通知）
- **RELEASE_INFO.json**: 读 zip 解压根目录的文件（构建时写入）
- **update_config.json**: 含 mirror_urls（主备双源）
- **/api/update/check**: 从 mirror 获取最新版本号，比较本地版本
- **/api/update/upgrade**: 下载新 zip → 解压覆盖 → 提示重启

### dist/ 目录（动态，非写死）
- 由 `build_release.py` 写入，`serve_mirror.py` 和 `/api/download/latest` 读取
- mirror 和 demo 下载都取 **最新 mtime** 的 zip（动态最新版）
- 发新版 → build_release 写新 zip → 自然成为最新
- 测试更新流程时需要新旧两个 zip 同时存在（旧版模拟客户，新版作为更新目标）

## 规则 1：做事前先查 mistake.txt

每次开始任何修改前，必须先读 `log/mistake.txt`，了解历史错误及避免方法，不得重复犯同样的错误。

## 规则 2：用户体验优先 & Playwright 真实测试（最高优先级）

> **用 Playwright 模拟用户的行为，检测所有按钮和显示。**
> 
> 这一条是铁律。任何 UI 功能完成后，必须在浏览器里点击每一个按钮、
> 检查每一段文字、验证每一个交互。curl API 返回 200 毫无意义——
> 用户看不到 API 响应，用户只看到页面。

- 所有测试必须用 Playwright 模拟真实客户点击网页和应用，验证完整的用户操作路径。
- **不可仅依赖 API 测试（pytest / Flask test client）就声称功能正常。**
- 必须验证以下各项无问题：
  - **每个按钮**点击有响应、状态正确切换
  - **每段文字**无乱码、无截断、内容正确
  - 业务逻辑正确、结果符合预期
  - 无文字/内容被遮盖
  - 无布局错乱、溢出或 z-index 冲突
  - **日志/回显区域**高度固定不随内容增长
- API 测试全绿 ≠ 用户能看到/用到功能。
- **每次声称"修复完成"前，必须贴出 Playwright 验证结果。**

## 规则 3：举一反三

当被指出一个错误时，必须主动思考：
- 其他场景是否有同样的问题？
- 其他版本（demo / release / 不同分支）是否有同样的问题？
- 其他类似代码/组件是否有同样的问题？

不得只修复当前指出的单点，必须系统性排查并修复所有同类问题。

## 发版（每次发版必须执行）

### 发版前置条件：模拟客户全量测试（必须通过才能发版）

**每次发版前，必须作为客户下载、解压并运行最新 release 版本，跑通全量测试。测试不通过 → 禁止发版。**

流程：

1. **构建新版本 zip**（如 `v1.1.x`）→ `dist/`
2. **解压 zip 到临时目录**（模拟客户下载后解压）
3. **启动 mirror 服务**: `py tools/serve_mirror.py --port 8000`
4. **用包内 Python 启动客户 portal**（不是源码目录的 portal）
5. **运行完整客户模拟测试**: `py application/test/portal/test_customer_full.py`
6. **验证结果**: 所有测试通过（更新检查、UI 交互、横幅、升级流程等）→ 才能继续发版

```powershell
# 完整客户模拟测试（解压 zip → 启动 → 检测更新 → 验证 UI）
# 必须通过才能发版
py application/test/portal/test_customer_full.py
```

> 注意: 不能用源码目录的 `py app.py` 或 `RELEASE_MODE=1` 绕过。必须是 zip 解压后的真实客户环境。

### 发版命令

**发版流程详见 [`RELEASE.md`](docs/RELEASE.md)。** 简要命令：

```powershell
git checkout release
py tools/release.py <version>       # 一键发版（构建+推送+验证）
py tools/release.py <version> --no-push   # 仅本地测试，不推送
```

发版脚本自动完成：切换分支 → 构建 → 注入 mirror 配置 → 提交 → 推送 → 验证。

## 项目文档索引

修改代码前，根据任务类型先读对应的文档：

| 文件 | 用途 | 何时读 |
|------|------|--------|
| [`RELEASE.md`](docs/RELEASE.md) | 发版流程、测试命令、架构图 | 发版前必读 |
| [`docs/`](docs/) | 项目文档（发版、检查清单、经历） | 查阅项目规范 |
| [`log/mistake.txt`](log/mistake.txt) | 历史错误记录及避免方法 | **每次修改前必读** |
| [`DESIGN.md`](DESIGN.md) | Cursor 设计系统（颜色/字体/间距/组件） | 任何 UI 修改前 |
| [`AGENTS.md`](docs/AGENTS.md) | AI agent 工作守则 | 了解行为边界 |
| [`README.md`](README.md) | 项目说明 | 了解项目概况 |
| [`framework/INTEGRATION.md`](framework/INTEGRATION.md) | 框架集成指南 | 修改框架/公共 CSS |
| [`plan/`](plan/) | 功能设计文档 & 规划文件 | 了解某个功能的设计意图 |
| [`log/`](log/) | 按日期记录的修改日志 | 追溯修改历史 |
| `application/*/DESIGN.md` | 各子应用的设计规范 | 修改子应用 UI |
| `application/*/plan/` | 各子应用的设计文档 | 了解子应用功能设计 |

## 测试命令速查

```powershell
# 全量 pytest（改代码后必跑）
py -m pytest application/test/ -v

# 完整客户模拟测试（解压 zip → 启动 → 检测更新 → 验证 UI）
# 必须通过才能发版
py application/test/portal/test_customer_full.py

# Portal 更新 UI Playwright 测试（真实浏览器点击按钮）
py -m pytest application/test/portal/test_update_ui_playwright.py -v

# 只跑 3 个子应用（快速验证）
py -m pytest application/test/test_report/ application/test/domain_capture/ application/test/config_analyzer/ application/test/portal/ -v

# config_analyzer 浏览器 E2E（不走 pytest）
py application/test/config_analyzer/test_e2e_playwright.py

# 构建后 zip 校验
py tools/_verify_zip.py dist/帮你节省5分钟-<version>.zip <version>
```
