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

## 规则 2：用户体验优先 & Playwright 真实测试

- 所有测试必须用 Playwright 模拟真实客户点击网页和应用，验证完整的用户操作路径。
- 不可仅依赖 API 测试（pytest / Flask test client）就声称功能正常。
- 必须验证以下各项无问题：
  - 按钮点击有响应
  - 业务逻辑正确、结果符合预期
  - 无文字/内容被遮盖
  - 无布局错乱、溢出或 z-index 冲突
- API 测试全绿 ≠ 用户能看到/用到功能。

## 规则 3：举一反三

当被指出一个错误时，必须主动思考：
- 其他场景是否有同样的问题？
- 其他版本（demo / release / 不同分支）是否有同样的问题？
- 其他类似代码/组件是否有同样的问题？

不得只修复当前指出的单点，必须系统性排查并修复所有同类问题。

## 发版（每次发版必须执行）

**发版流程详见 [`RELEASE.md`](RELEASE.md)。** 简要命令：

```powershell
git checkout release
py tools/release.py <version>       # 一键发版（构建+推送+验证）
py tools/release.py <version> --no-push   # 仅本地测试，不推送
```

发版脚本自动完成：切换分支 → 构建 → 注入 mirror 配置 → 提交 → 推送 → 验证。

## 测试命令速查

```powershell
# 全量 pytest（改代码后必跑）
py -m pytest application/test/ -v

# 完整客户模拟测试（解压 zip → 启动 → 检测更新 → 验证 UI）
# 必须通过才能发版
py application/test/portal/test_customer_full.py

# 只跑 3 个子应用（快速验证）
py -m pytest application/test/test_report/ application/test/domain_capture/ application/test/config_analyzer/ application/test/portal/ -v

# config_analyzer 浏览器 E2E（不走 pytest）
py application/test/config_analyzer/test_e2e_playwright.py
```
