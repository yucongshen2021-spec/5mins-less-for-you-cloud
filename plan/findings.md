# Findings & Decisions — 项目工具&目标管理文档化

## Requirements
- 统一管理所有测试工具（pytest, Playwright, smoke tests, E2E, 构建验证等）
- 文档化每个按钮的功能和预期结果，绑定测试工具
- 测试必须覆盖逻辑部分（后端脚本功能）和用户视角（前端联动）
- 固化更新模块流程，确保每次更新无差错

## Research Findings

### 项目架构
- **Portal**: Flask 应用，端口 5000(demo)/7000(release)，聚合 4 个子应用
- **4 个子应用**: 配置生成(all_in_one)、测试报告(test_report)、域名抓取(domain_capture)、配置梳理(config_analyzer)
- **双版本**: Demo (5000-5004) + Release (7000-7004)
- **更新模块**: update_check.py + upgrade.py + serve_mirror.py（仅 release 版）

### 测试文件分布（38 个文件）
- all_in_one: 18 个测试文件（107+ cases）
- portal: 8 个测试文件（smoke, update_ui, upgrade, customer_full, release, zip, update_e2e, update_flow）
- test_report: 2 个测试文件（smoke + api）
- domain_capture: 2 个测试文件（smoke + api）
- config_analyzer: 2 个测试文件（smoke + e2e_playwright）
- 根层: 2 个共享文件（_smoke_helpers.py, 框架）

### 按钮功能清单（从 index.html 提取）
**Header 区域:**
1. ☰ toggleSidebar → 收起/展开侧栏
2. ? toggleHelp → 帮助面板弹出/关闭
3. Release: 手动检查版本按钮
4. Release: 更新横幅（有新版本时出现）

**侧栏区域:**
5. 4 个 nav-item → 切换子应用 iframe
6. Demo: dlCard → 下载完整应用 zip
7. Release: upgradeBtn → 5 态更新按钮
8. Release: btnCheckUpdate → 手动检查版本

**JavaScript 功能:**
9. 健康检查定时器（10s）
10. 更新检查定时器（5s 首次 + 每小时）

### 更新模块组件
- update_check.py: 版本检查（多源 fallback）
- upgrade.py: 升级执行（下载 → 解压 → 替换 → 重启）
- serve_mirror.py: mirror 服务器（端口 8000）
- update_config.json: mirror URL 配置
- .update_cache.json: 检查结果缓存

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| 测试工具分 5 类管理 | 职责清晰：代码逻辑/用户行为/构建验证/更新链路/启动验证 |
| 按钮按页面区域分组 | 便于定位和维护 |
| 更新流程用状态机描述 | 已有 5 态定义，直接文档化 |
| 每个测试必须绑定到具体功能点 | 确保全量覆盖，无遗漏 |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| session-catchup.py 命令格式错误 | 跳过，直接创建新 plan |
| 习惯性并行工具调用失败 | 改为顺序调用修复 |

## Resources
- `log/mistake.txt` — 48 条历史错误记录
- `plan/full-testing-standard.md` — 已有全量测试标准（201 lines）
- `plan/demo-release-split.md` — 双版本分离设计
- `DESIGN.md` — Cursor 设计系统
- `RELEASE.md` — 发版流程
- `application/portal/app.py` — Portal 后端
- `application/portal/templates/index.html` — Portal 前端（799 lines）
- `application/portal/update_check.py` — 更新检查模块
- `application/portal/upgrade.py` — 升级模块
