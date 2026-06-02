# 帮你节省5分钟 — 项目规则

## 版本架构（最高优先级）

项目有 **两个版本**，严格分离，不可混淆：

### Demo 版（开发/试用）
- **端口**: 5000（portal）+ 5001-5004（子应用）
- **启动**: 源码直接运行 `py application/portal/app.py`
- **RELEASE_MODE**: 不设置
- **页面**: DEMO 橙色标签、"demo试用版"、左下角下载卡片
- **下载**: 左下角按钮 → 从 `dist/` 下载 **唯一正式版** zip
- **更新检查**: **不做**（无更新横幅、无检查按钮、无自动检查）
- **RELEASE_INFO.json**: 读项目根目录的文件
- **dist/**: 只放 **一个** 正式版 zip

### Release 版（客户交付）
- **端口**: 7000（portal）+ 7001-7004（子应用）
- **启动**: 解压 zip → 双击 `start_all.bat`（自动设 RELEASE_MODE=1）
- **RELEASE_MODE**: 自动设置（便携 Python 存在时）
- **页面**: RELEASE 绿色标签、"正式版"、手动检查版本按钮
- **更新检查**: **必须做**（5 秒自动检查 + 手动按钮 + 横幅通知）
- **RELEASE_INFO.json**: 读 zip 解压根目录的文件（构建时写入）
- **update_config.json**: 含 mirror_urls（主备双源）

### dist/ 目录规则
- 正常情况下 **只有一个** zip：当前正式版
- 测试更新流程时 **临时** 放 2 个 zip（旧版 + 新版），测完立即删除新版
- mirror 扫描 `dist/` 最新 mtime 的 zip 作为"最新版"
- 绝对不允许测试版 zip 长期留在 dist/

### 发版流程
1. 改 RELEASE_INFO.json → 新版本号
2. `py tools/build_release.py --version vX.Y.Z --mirror-url http://192.168.5.10:8000/api/update/manifest`
3. git commit + push
4. dist/ 保持只有正式版 zip

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

## 测试命令速查

```powershell
# 全量 pytest（改代码后必跑）
py -m pytest application/test/ -v

# 只跑 3 个子应用（快速验证）
py -m pytest application/test/test_report/ application/test/domain_capture/ application/test/config_analyzer/ application/test/portal/ -v

# config_analyzer 浏览器 E2E（不走 pytest）
py application/test/config_analyzer/test_e2e_playwright.py
```
