# 系统级清理与整改 Plan（交接版）

> **目的**：为项目交接做一次完整、系统的清理整改——理解全部细节，清除所有不需要、过时、错误的文件 / 文档 / 配置 / 表述。
> **铁律**：**绝不删除或改动有用的东西**。一切判断必须有证据；一切清理必须可回滚。
> **制定日期**：2026-10-12（基于对活系统的全面侦察）
> **决策记录（2026-10-12 用户确认）**：
> - D1 SECRET_KEY：**保持不变**（用户决定；文档改为如实描述当前机制）
> - D2 版本号：**更新为 2.0.0**
> - D3 停用应用：**保留在 application/ + 文档标注**
> - D4 test/portal PNG：**删工作区文件**（git 历史保留）
> - D5 /home/ubuntu：**删 er4/er5 会话产出物，保留两个 git 克隆**
> - 新增需求：门户顶栏「DEMO」徽标后增加 **「BY YUC」**（随批次 2 实施）
> **执行状态**：✅ **已全部完成（2026-10-12）**——批次 0~6 全部执行，测试全绿（280/86/147 + CI 模拟 0 失败），生产零事故。结果与验证数据见 `docs/CLEANUP_REPORT.md`；逐批留痕见 `log/2026-10-12-cleanup.md`。
>
> **执行期重要修正**：批次 4 的孤儿判定被 `_DISK_ALIASES`（web/app.py 磁盘别名映射）反转——"旧名"目录 `ER_FastIP___*` 等才是现役，真正未用的是 11 个"新名"目录（详见 `.archive/orphans-20261012/MANIFEST.md`）。此修正体现了"三重验证"安全协议的必要性。

---

## 一、系统全貌（侦察结论，2026-10-12 实测）

| 项目 | 实际情况 |
|---|---|
| 容器 | `fivemins-portal`（5000+9000，healthy）/ `fivemins-portal-test`（8000+8001，healthy）/ `fivemins-port80-test`（80）|
| 镜像 | fivemins-portal / fivemins-portal-test / python:3.11-slim / **fivemins-test-portal-test（疑似陈旧）** |
| 场景 | **31 个**（活系统 `/api/scenarios` 实测），5 工具，6 个生成器源码文件 |
| 数据库 | auth.sqlite + stats.sqlite（portal/logs 卷）；23 用户、540+ 生成记录 |
| 备份 | root crontab 09:00/21:00 → tools/db_backup.py；14 天保留 + 周备份 |
| CI | GitHub Actions：**58 次运行全部失败**（2026-06-16 建库至 07-23，从未绿过）——根因已定位（见 P4.1）|
| 宿主目录 | .wine64 743M + .build_cache 144M（exe 重建工具链，保留）；db_backup 254M |
| GitHub | 仓库已转 public；本地领先 origin/main 6 个提交 + HISTORY.md 未提交 |

---

## 二、问题清单（四类，全部带证据）

### P1 文档过时 / 错误（要改，纯文本）

| # | 位置 | 问题 | 修正 |
|---|---|---|---|
| 1 | README.md:65,91 | 「5 工具 × 29 场景」「级联菜单 29 场景」 | 31 场景；工具变体表补 ER IPSec ×4、ER5 HK·IPSec |
| 2 | README.md:146,165 | 「comprehensive.py（185 个）」 | 280 个（实测） |
| 3 | README.md 服务表 | 缺 fastip_report 5006 | 补一行 |
| 4 | README.md 目录结构 | 缺 fastip_report、port80-test；`editor_defaults/` 画在错误层级（实际在 `data/` 下）；supervisord 描述缺 fastip_report | 修正 |
| 5 | README.md 环境变量表 | 「SECRET_KEY 默认 随机」与实际 compose 的 `change-me-in-production` 不符 | 随 D1 决策一并修正 |
| 6 | docs/AGENTS.md:115 | 「comprehensive 185 个」 | 280 |
| 7 | docs/AGENTS.md 服务表 | 缺 fastip_report 5006 | 补 |
| 8 | docs/AGENTS.md Git Push 段 | IP 列表 140.82.112.x 已全部失效（现为 20.27.177.113，且会漂移） | 改为「探测式」写法（for 循环探 /dev/tcp 多个候选）|
| 9 | docs/AGENTS.md 测试命令 | `sudo docker-compose`（v1 语法） | `sudo docker compose`（v2） |
| 10 | application/all_in_one - cc/README.md:23 | 「29 场景」 | 31；页签表缺 ER5.0 与 IPSec 变体说明 |
| 11 | test_features.md 整篇 | 7-21 手写验收清单：29 场景、AR SD-WAN 可点（现已「测试中」禁用）、无 playwright 环境说明 | 重写为验收清单 v2 或移入 docs/archive/（决定见 D3 同理） |
| 12 | docs/whatsnew/updates.json | 「最近更新」停在 7-20 | 补 7-21 ~ 10-12 重要更新（页签关闭、80 页面、DNS/MSS 变更等） |
| 13 | MIGRATION_TO_LINUX.md | 已自标「迁移蓝图（已完成）…历史参考」但含大量过时段落（8 worker、5001-5004 端口表、Xvfb） | 移动至 `docs/archive/`（正文不改，保持历史原貌） |
| 14 | HISTORY.md | 需补充：CI 全红发现、本次清理里程碑 | 追加条目（只增不改） |

### P2 配置 / 注释错误（要改）

| # | 位置 | 问题 | 修正 |
|---|---|---|---|
| 1 | docker/supervisord.conf:16 | 注释「gunicorn 启 8 个 worker」 | 16（env `GUNICORN_WORKERS=16`） |
| 2 | docker-compose.test.yml:4 | 注释「子应用 5001-5004 由 supervisord 拉起」 | 5003 / 5005 / 5006 |
| 3 | application/portal/process_manager.py | 注释「Demo version shows only all_in_one」 | 实际 3 个可见应用（5003/5005/5006） |
| 4 | docker-compose.yml | `SECRET_KEY=change-me-in-production`——**这是生产真实会话密钥**（env 优先级最高，见 portal/app.py:41-51），stats 也回退到它 | 见决策点 **D1** |
| 5 | tools/db_backup.py `cleanup_old_backups()` | **Bug**：`f.suffix in ("-wal","-shm")` 永不命中（`Path("x.sqlite-wal").suffix == ".sqlite-wal"`）→ 56 个残留 -wal/-shm 从不清理 | 改 `f.name.endswith(("-wal","-shm"))`；存量 56 个文件先 sqlite3 integrity 校验再清 |
| 6 | FAQ：`_templates.json` | src/_templates.json（78K，6-16）全仓无引用（`_templates` 字符串亦无匹配）→ 见 P3.2 | 二次验证后归档 |
| 7 | /etc/hosts | `20.27.177.113 github.com`（服务器级；会漂移） | 不改动，写入 HANDOVER.md 运维章节（探测更新步骤） |
| 8 | 疑似陈旧镜像 | `fivemins-test-portal-test:latest`（760MB，无容器使用） | 与 D5 一起拍板（建议 `docker image rm`） |

### P3 孤儿 / 垃圾文件（先核验 → 归档到 .archive/，**不直接删**）

| # | 对象 | 证据 | 处置 |
|---|---|---|---|
| 1 | **editor_defaults 11 个疑似孤儿目录**（40 个目录 = 29 个现役目录 + 11 个旧命名孤儿） | safe_key 映射公式已确认（web/app.py:2157 `re.sub(r"[^\w一-鿿]", "_", key)`）；逐目录映射得出 29 个现役、11 个旧命名：`ER_FastIP___HK_香港出口`、`ER_FastIP___非HK出口`、`ER_FastIP___非HK出口_单出口`、`ER_FastIP_5_0___ER_域名分流`、`ER_FastIP_5_0___HK_香港出口`、`ER_FastIP_5_0___HK_香港出口_IPSec`、`ER_FastIP_5_0___非HK出口`、`ER_MPLS___国内配置`、`ER_MPLS___海外配置`、`USG_FastIP___非HK出口`、`AR_传统组网` | 三重核验（映射证明 + 全仓 grep + 内容比对）后整体归档，附 MANIFEST |
| 2 | src/_templates.json（78K） | 全仓 grep `_templates.json` 0 引用 | 二次 grep（含字符串拼接形式 `"_templates"`）后归档 |
| 3 | 「自动做测试报告 - cc/log/」下 6 个伪日期目录：`20990101_CONCUR_0`、`20990101_TEST_LINE`、`20990102_CONCUR_1`、`20990103_CONCUR_2`、`20990615_NO_CID`、`20991231_DIR_TEST` | 2099 年假日期 = 历史测试残留；该目录整体被 .gitignore；未跟踪 | 核验 test_report 测试不依赖后归档 |
| 4 | db_backup/ 下 56 个 -wal/-shm 遗留（28+28） | 对应 .sqlite 已被 14 天保留策略清掉，sidecar 因 P2.5 的 bug 留下 | 随 P2.5 修复一起清理（先 integrity 校验） |
| 5 | application/test/all_in_one/{logs,results}/ 运行产物（14 txt + 3 json） | compare.py 每次运行重新生成（compare.py:11,181-199）；未跟踪 | 清理（可从 git 外再生） |
| 6 | application/test/portal/*.png（2 张，6 月截图，**已跟踪**） | 见 D4 | 待拍板 |
| 7 | dist/（空目录）、temp/（仅 .gitkeep） | dist 无引用；temp 是约定目录 | dist 归档；temp 保留（.gitkeep） |
| 8 | 宿主 __pycache__ / .pytest_cache（.gitignore 内） | 可再生 | 低风险清理 |
| 9 | 根 plan/ 8 个 6 月方案 + 各应用内 plan/、log/ 历史目录 | AGENTS.md 约定 plan/ 用于新方案落档（约定仍在用）；其中历史 6 月文档已完结 | 历史归档到 `plan/archive/`（保留目录约定） |

> **注**：40 个目录与 31 场景并非一一对应——部分现役场景（如「单出口」「ER5 HK·IPSec」）本就没有磁盘覆盖目录（用源码内置模板）。核验时以「该目录名能否被任何现役 safe_key 匹配」为准，不以"场景没有目录"为异常。

### P4 工程缺陷（要修 / 要验证）

| # | 对象 | 结论 | 动作 |
|---|---|---|---|
| 1 | **GitHub Actions 58/58 全失败（从未绿过）** | **根因已定位（双重）**：① pytest.ini 的 `--ignore=application/test/...` 路径按仓库根目录书写，而 CI 的 working-directory 是 `application/test`，`--ignore` 路径解析失效 → `test_e2e_playwright.py` 仍被收集；② 该文件顶层 `from playwright.sync_api import ...`，CI 环境未装 playwright → **collect 阶段 ImportError** → “Show test inventory” 步骤失败（exit 2），pytest 正式阶段被 skip。全部 58 次的失败形态一致 | 修复三件套：a. 该文件改为 `pytest.importorskip("playwright")`（防任何 cwd 下爆炸）；b. workflow 改为在**仓库根**运行 `python -m pytest application/test -q`（使 pytest.ini 忽略路径生效）；c. 为 `blackbox_8000/test_full_api.py` 补会话级 skip 守卫（其 `_req` 只捕获 HTTPError，容器不在时 URLError 会导致 CI 红；multiuser 已有 `container_up` fixture 可复用模式）。修完本地模拟 CI 全命令至绿 |
| 2 | 停用应用 5001/5002/5004（域名抓取/测试报告/配置梳理） | 设计为「已停用、代码保留、supervisord 注释可恢复」；其测试目录仍在 test/ 下且能被收集 | 保留（现状合理）；在 HANDOVER.md 写明恢复方法；其测试保持收集（本地验证 333 收集成功） |
| 3 | .wine64 + .build_cache（887M） | 是 5006 应用 zip 内 exe 的唯一重建工具链（log/2026-07-27.md 有完整记录） | 保留；提炼 `docs/REBUILD_EXE.md`（打包命令 + 验证方法） |
| 4 | port80-test/ | 无 README、无 compose 文件、根 README 未收录 | 补 `port80-test/README.md`（用途/docker run 命令/隔离声明）+ README 服务表补 80 端口行 |
| 5 | RELEASE_INFO.json（v1.2.3） | **在用**：portal/app.py:62 读取并在首页顶栏显示 `v1.2.3 · Demo`——但 1.2.3 是桌面版版本号 | 见决策点 **D2** |
| 6 | 测试数口径 | comprehensive 280 / blackbox 86（含并发 28）/ pytest 147 | 统一写进 README、AGENTS、all_in_one README |
| 7 | pytest.ini 忽略清单 | 引用的文件均存在（已核）；但路径依赖「从仓库根运行」未写明 | 在 pytest.ini 注释 + AGENTS 说明该约束（配合 P4.1） |

---

## 三、明确「不动」的东西（同等重要）

1. **历史记录只读**：`log/*.md`、`log/mistake.txt`、`docs/经历.md`、`HISTORY.md` 已有条目——历史原貌不修改，新变更只追加。
2. **用户数据**：`data/users/`、`data/editor_workspace/`、auth.sqlite、stats.sqlite、db_backup 现有备份——只读不动。
3. **停用应用源码**、**wine/build_cache**、**port80-test 运行中的容器**——保留。
4. **生产容器当前运行配置**——除 D1（密钥）外不改；一切改动先过 8000。
5. **git 历史**——不做 rebase/filter 之类改写；只做新提交。

---

## 四、实施批次（每批含独立验证门槛，随时可停）

### 批次 0 · 冻结与基线（先做，再动任何东西）
- git bundle 全量备份；工作区 tar（排除 .wine64/.build_cache/db_backup）→ `/opt/fivemins/.archive/backup-20261012/`
- 手动执行一次 `db_backup.py --check` 记录备份基线
- 记录基线数据：31 场景 / 测试数（280+86+147）/ editor_defaults 40 目录清单 / 文件清单
- **验证**：bundle 可 verify、tar 可解包

### 批次 1 · 文档修正（P1 全部，纯文本零功能影响）
- **验证**：逐条 diff 核对（改动清单存档）；按修正后的 README 命令抽跑 1 条

### 批次 2 · 配置与注释修正（P2.1/2/3 + P2.5）
- db_backup bug 修复 + 存量 56 个 sidecar 清理（先逐个 `sqlite3 "PRAGMA integrity_check"` 关联 sqlite 确认无损）
- **验证**：手动跑 `db_backup.py` 一次（应成功清理且备份 OK）；8000 重建 → blackbox 86 绿

### 批次 3 · CI 修复与工程收尾（P4.1/3/4 + P2.6）
- **验证**：本地以 CI 等价环境（无 playwright、无浏览器）跑完整 workflow 命令至绿；db_backup --check

### 批次 4 · 孤儿核验与归档（P3 全部，**最谨慎批次**）
- 每个对象执行「三重验证」：**(a)** 代码级引用证明（全仓 grep，含字符串拼接变体）**(b)** 运行态证明（safe_key 映射推演 / 活系统行为）**(c)** 内容对照（与现役模板/源码 diff，注明来源）
- 全部 `mv` → `/opt/fivemins/.archive/orphans-20261012/`（保留原目录结构 + `MANIFEST.md` 逐一说明来源与证据）
- **验证**：归档前后对 31 场景做全量生成**逐字节 diff**（一致才通过）；「恢复出厂」抽查 3 个场景；8000/5000 冒烟
- **本批次不删任何东西**；冷静期 30 天后经确认再议物理删除

### 批次 5 · 交接文档包
- `docs/HANDOVER.md`：架构总览 / 账号与密码位置 / 端口表 / 数据模型 / 日常运维（备份·恢复·日志·发布）/ 部署步骤 / GitHub 与 CI / 已知问题与决策记录
- `docs/REBUILD_EXE.md`（P4.3）、`port80-test/README.md`（P4.4）
- **验证**：按 HANDOVER.md 从零走「克隆 → 部署 → 测试 → 冒烟」全流程一遍

### 批次 6 · 终验与报告
- 全测试（280/86/147）+ 页面冒烟（5000/8000/80）+ CI 推送后确认绿
- 产出 `CLEANUP_REPORT.md`（改了什么 / 归档了什么 / 为什么 / 如何恢复）
- git 提交（推送通道见 D6）；HISTORY.md 追加本次里程碑

---

## 五、安全协议（防「翻出错误」，写死执行）

1. **删除禁令**：清理 = `mv` 到 `.archive/`，禁止 `rm -rf`；30 天冷静期。
2. **三重验证**：任何对象判定「孤儿/过时」前必须有代码引用证明 + 运行态证明 + 对照证明，三者缺一 → 保留观察。
3. **历史保护**：log/、mistake.txt、经历.md、HISTORY.md 已有内容只增不改。
4. **生产隔离**：代码/配置先 8000 验证全绿 → 才同步 5000；数据操作先备份。
5. **批次留痕**：每批改动前出清单、后出 diff，存档到 `log/2026-10-12-cleanup.md`。
6. **不确定即保留**：列入「待观察」清单，绝不硬删。

---

## 六、需你拍板的决策点

| # | 决策 | 选项 | 我的建议 |
|---|---|---|---|
| D1 | 生产 SECRET_KEY（现为 `change-me-in-production`） | ①改强随机（全员需重登一次）②保持现状 | **改**（随交接一次做完） |
| D2 | 首页版本号 v1.2.3（桌面版号） | ①更新为 2.0.0 并注明 ②保留原状+注释说明 | **更新为 2.0.0** |
| D3 | 停用应用 5001/5002/5004 | ①保留在 application/（现状+文档标注）②移入 archive/ | **①保留**（恢复成本最低） |
| D4 | test/portal/*.png（2 张 6 月截图，已跟踪） | ①工作区删除（git 历史保留）②保留 | **①删除** |
| D5 | /home/ubuntu 4 个杂项：er4-fastip-nonhk-singlenatpe、er5-fastip-hk-ipsec（会话产出物）；fastip-auto-test-report、usg-virus-test（git 克隆） | 逐个定去留 | **删前两个、留后两个** |
| D6 | 完成后 git 提交推送 | ①随批次提交，最后统一推送 ②只提交不推送 | 需要推送通道（SSH key 已就绪待加） |

---

## 七、验收标准（DoD）

1. **文档一致**：P1 清单逐条核销，所有现行文档与运行态零出入。
2. **测试全绿**：comprehensive 280 + blackbox 86 + pytest 147。
3. **CI 绿**：GitHub Actions 上出现历史上第一次绿色（公开可查）。
4. **无悬案**：editor_defaults 40 目录全部有结论；归档目录带完整 MANIFEST；不存在「不知道能不能删」的文件。
5. **可交接**：HANDOVER.md 可从零复现部署；REBUILD_EXE.md 可复现打包。
6. **零误伤**：用户数据、模板、会话全程不受影响；31 场景生成与清理前逐字节一致。
