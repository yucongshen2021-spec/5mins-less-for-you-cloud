# 系统级清理与整改 · 结果报告（交接版）

> 依据 `docs/CLEANUP_PLAN.md` 执行；逐批留痕见 `log/2026-10-12-cleanup.md`；归档清单见 `.archive/orphans-20261012/MANIFEST.md`。
> **日期**：2026-10-12 ｜ **结果**：全部批次完成，生产零事故，测试全绿。

---

## 一、交付摘要

| 类别 | 结果 |
|---|---|
| 文档一致性 | README / AGENTS / all_in_one README / test_features / whatsnew / MIGRATION 全部核对修正（29→31 场景、185→280 测试、服务表补 5006/80、Git push IP、docker-compose 命令形、禁用页签状态等 14 项） |
| 配置与代码 | supervisord/compose/process_manager 过期注释修正；db_backup 清理 bug 修复；RELEASE_INFO → 2.0.0；BY YUC 徽标上线 |
| CI | 修复 GitHub Actions 历史 58/58 全红（根因双点：CI 无 playwright + `--ignore` 路径失效）；本地模拟 **184 passed / 116 skipped / 0 failed**；**GitHub 实跑 success（run 38333456696，历史首次绿）** |
| 归档 | 11 个未用模板目录、8 个历史方案、2 张旧截图、56 个备份残留、2 个首页杂项、1 个陈旧镜像（760M→归档 tar）|
| 新增文档 | `docs/HANDOVER.md`（交接手册）、`docs/REBUILD_EXE.md`、`port80-test/README.md`、`docs/CLEANUP_PLAN.md`、本报告 |
| 冻结备份 | `.archive/backup-20261012/`（git bundle 4.4M + 工作区 tar 46M/2136 项，均已验证可解包） |

## 二、关键验证数据（2026-10-12 实测）

| 项 | 结果 |
|---|---|
| comprehensive（容器内） | **280 passed / 0 failed** |
| blackbox_8000（对重建后的 8000） | **86 passed**（含 28 项多用户并发） |
| pytest all_in_one（仓库根口径） | **147 passed / 17 skipped**（浏览器用例自动跳过） |
| CI 等价模拟（无 playwright、无容器） | **184 passed / 116 skipped / 0 failed / 0 error** |
| 生产发布验证 | v2.0.0 显示 ✓、BY YUC 徽标 ✓、whatsnew 新条目渲染 ✓、健康检查 ✓、**23 用户数据完好** ✓ |
| db_backup | 修复后实跑通过：备份 + 完整性校验 + 56 个残留 sidecar 清零（0 残留） |

## 三、归档与还原（30 天冷静期至 2026-11-11）

| 归档物 | 位置 | 还原方法 |
|---|---|---|
| 11 个未用模板目录 | `.archive/orphans-20261012/editor_defaults_unused/` | `mv` 回 `application/all_in_one - cc/data/editor_defaults/`（⚠️ 先读 MANIFEST 的别名警告） |
| 测试产物/截图/plan 历史 | `.archive/orphans-20261012/test_artifacts/`、`plan/archive/`（git 内） | 按 MANIFEST；或 `git show` 找回 |
| 陈旧镜像 | `.archive/images/fivemins-test-portal-test-20261012.tar` | `sudo docker load -i <tar>` |
| 全量备份 | `.archive/backup-20261012/` | `git bundle` 克隆 / tar 解包 |
| 首页杂项文件 | `.archive/home-cleanup-20261012/` | `mv` 回 `/home/ubuntu/` |

## 四、重要机制沉淀（详见 HANDOVER §二）

1. **`_DISK_ALIASES` 别名系统**：现役模板磁盘目录部分使用旧命名；判断目录去留必须以该表为准（本次归档误判修正的第一依据）。
2. **容器卷 ≠ 仓库 data/**：生产数据在 Docker 命名卷；仓库 `data/` 为裸机副本 + 新部署卷种子。
3. **CI 运行口径**：workflow 从仓库根运行为准（pytest.ini 忽略路径依赖仓库根）；浏览器/容器依赖用例自动跳过。

## 五、后续建议

1. **push 通道**：将 `~/.ssh/id_ed25519.pub` 加入 GitHub Deploy keys（勾选 write access）后推送本次全部提交；或在服务器放新的 PAT。
2. SECRET_KEY（当前保持 `change-me-in-production`，用户决策）：如交接后安全评审要求轮换，按 HANDOVER §三操作（全员重登一次）。
3. ER FastIP 5.0 / AR SD-WAN 验收完成后，在 `web/templates/index.html` 移除 `disabled` + 「测试中」徽标即可开放。
