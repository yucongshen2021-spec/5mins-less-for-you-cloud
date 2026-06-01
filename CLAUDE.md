# 帮你节省5分钟 — 项目规则

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
