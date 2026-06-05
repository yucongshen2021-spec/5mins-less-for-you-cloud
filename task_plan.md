# Task Plan: 项目工具&目标管理文档化

## Goal
创建项目治理文档体系——统一管理所有测试工具、文档化每个按钮功能&预期结果&测试绑定、固化更新模块流程，确保以后每次开发和发版都有据可依。

## Current Phase
Phase 3

## Phases

### Phase 1: 项目结构理解 & 需求梳理
- [x] 读取 log/mistake.txt（48 条历史错误）
- [x] 读取现有 plan/ 目录文档
- [x] 读取所有关键源码文件（app.py, update_check.py, upgrade.py, index.html, DESIGN.md）
- [x] 梳理测试文件结构（38+ 测试文件）
- [x] 梳理应用目录结构（5 个子目录）
- **Status:** complete

### Phase 2: 创建项目治理文档体系
- [x] 创建 `plan/project-governance.md` — 项目功能全览 & 按钮功能文档 & 测试绑定
- [x] 创建 `plan/test-management.md` — 统一测试工具管理
- [x] 创建 `plan/update-process.md` — 更新模块流程固化
- **Status:** complete

### Phase 3: Review & 验证
- [x] 对照 mistake.txt 检查文档完整性
- [x] 确认所有按钮覆盖、所有测试绑定
- [x] 确认更新流程完整覆盖
- **Status:** complete

## Key Questions
1. 每个按钮的预期行为是什么？（已从 index.html + app.py 提取）
2. 哪些测试覆盖了哪些功能？（已从 38 个测试文件梳理）
3. 更新流程有哪些关键步骤？（已从 update_check.py + upgrade.py + RELEASE.md 提取）
4. 测试工具如何分类管理？（需在 Phase 2 中定义）

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| 文档放在 `plan/` 目录 | 符合 Rule 3 要求 |
| 三份文档：治理 + 测试管理 + 更新流程 | 职责分离，便于独立维护 |
| 每个按钮绑定到具体测试 | 确保测试不遗漏功能点 |
| 更新流程用状态机描述 | 5 态按钮已有明确定义 |

## Notes
- 项目有 demo (500x) 和 release (700x) 两个版本，文档需要双版本覆盖
- 更新模块仅 release 版启用
- 测试必须覆盖逻辑层（pytest）和用户层（Playwright）
