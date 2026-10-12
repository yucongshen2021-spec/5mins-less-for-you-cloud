# HANDOVER · 交接手册

> **项目**：帮你节省5分钟 · 网络设备配置生成平台
> **服务器**：腾讯云 Ubuntu（VM-0-15-ubuntu，4 核 / 3.6G，公网 119.91.151.211），部署目录 `/opt/fivemins`
> **编写日期**：2026-10-12（系统级清理整改同日完成，记录见 `docs/CLEANUP_REPORT.md`）
> **配套文档**：`README.md`（快速开始）· `docs/AGENTS.md`（工程守则）· `docs/DESIGN.md`（UI 规范）· `HISTORY.md`（上线全纪录）· `log/mistake.txt`（历史踩坑）

---

## 一、产品是什么

把网络工程师每次约 5 分钟的「照抄配置」变成 30 秒的「粘贴数据头 → 一键出配置」。

- **用户流程**：登录 5000 → 选工具/变体 → 粘贴设备数据头 → 调参数 → 生成 → 复制/导出配置脚本
- **覆盖**：VyOS（ER 4.0 / 5.0）、华为 USG、AR（SD-WAN / 传统组网）、MPLS —— 5 个工具、**31 个场景**
- **规模**（2026-10-12）：23 个注册用户、540+ 次生成记录
- **形态**：Docker 单容器多应用（Flask + supervisord + gunicorn），浏览器使用

## 二、系统架构

```
浏览器 ──► 5000 Portal（Flask，统一入口 / 登录鉴权 / 反向代理 /app/<id>/）
              │
              ├─► 5003 all_in_one（配置生成；gunicorn 16 worker，独立进程隔离）
              ├─► 5005 usg_virus_test（USG 测病毒指引页 + 工具包下载）
              ├─► 5006 fastip_report（FASTIP 测试报告指引页 + 桌面版下载）
              └─► 9000 stats（统计看板 / 分权后台，仅绑定 127.0.0.1，经 Portal 反代访问）

supervisord（容器内）：portal + all_in_one + usg_virus_test + fastip_report + stats
                       停用应用（5001/5002/5004）以注释保留在 docker/supervisord.conf
独立容器：fivemins-port80-test（80 端口连通性测试页，见 port80-test/README.md）
```

### 关键机制（交接重点）

1. **模板三层体系**：出厂模板（源码内置）→ 磁盘出厂目录（`data/editor_defaults/`，运行态在 Docker 卷）→ 用户工作区（`data/users/<uid>/editor_workspace/`）。
2. **⚠️ 磁盘别名系统 `_DISK_ALIASES`**（`application/all_in_one - cc/web/app.py`）：部分场景的磁盘目录名是**旧命名**（如 `ER_FastIP___HK_香港出口` 是现役目录，`Epoch_FastIP___HK_香港出口` 反而未用）。判断"哪些模板目录在用"**必须以该映射表为准**，切勿按名字新旧直觉判断。历史误判与已归档清单见 `.archive/orphans-20261012/MANIFEST.md`。
3. **容器卷 ≠ 仓库 data/**：库里 `application/all_in_one - cc/data/` 是"裸机/测试运行的副本 + 新部署的卷种子"；**生产运行数据在 Docker 命名卷里**（见第五节）。改模板要同步到卷（见第六节）。
4. **多 worker 热更新**：模板/参数保存后通过 mtime 轮询自动生效，无需重启。

## 三、账号与密钥

| 项 | 值 / 位置 | 说明 |
|---|---|---|
| 管理员账号 | `yucs` / `ADMIN_PASSWORD`（默认 `yucs123`） | 首次部署自动创建；建议交接后修改 |
| 管理后台密码 | 同上（9000 `/admin`） | 独立 session + 审计日志 |
| 测试账号 | `test*` / `ctest*` 开头 | 不记录日志 |
| SECRET_KEY | `docker-compose.yml` 中 `SECRET_KEY=change-me-in-production` | **用户决策（2026-10-12）：保持不变** |
| 密钥机制 | 代码优先级：env `SECRET_KEY` → `portal/logs/.secret_key` 文件 → 随机生成 | 若要轮换：改 compose env 并 `up -d`（全员需重登一次） |

## 四、端口与服务

| 端口 | 服务 | 状态 |
|---|---|---|
| 5000 | Portal（生产入口） | ✅ 运行 |
| 5003 | all_in_one（容器内端口） | ✅ 运行 |
| 5005 | usg_virus_test | ✅ 运行 |
| 5006 | fastip_report | ✅ 运行 |
| 9000 | stats（仅 127.0.0.1） | ✅ 运行 |
| 80 | 连通性测试页（独立容器） | ✅ 运行 |
| 8000 → 5000 / 8001 → 9000 | 测试环境（fivemins-portal-test） | ✅ 运行 |
| 5001 / 5002 / 5004 | 域名抓取 / 测试报告 / 配置梳理 | ⏸ 已停用（supervisord 注释可恢复） |

## 五、数据与备份（动数据前必读）

### 数据位置

| 数据 | 容器内路径 | 宿主（Docker 卷） |
|---|---|---|
| 用户账号 DB | `/app/application/portal/logs/auth.sqlite` | 卷 `fivemins_portal-logs` |
| 统计/审计 DB | `/app/application/portal/logs/stats.sqlite` | 卷 `fivemins_portal-logs` |
| 全部应用运行数据 | `/app/application/all_in_one - cc/data/`（users 工作区、editor_defaults、whatsnew 等） | 卷 `fivemins_portal-data` |
| 测试环境同结构 | —— | 卷 `fivemins_portal-test-data` / `fivemins_portal-test-logs` |

> 查看卷路径：`sudo docker volume inspect fivemins_portal-data`。

### 备份机制（已配置，自动）

- **root crontab**：每天 09:00 / 21:00 执行 `python3 /opt/fivemins/tools/db_backup.py`
- 策略：容器内 `sqlite3 backup()` 热备 → `docker cp` 到 `/opt/fivemins/db_backup/` → 完整性校验（immutable 模式）
- 保留：普通备份 14 天；每周一自动另存 `weekly/` 永久保留
- 日志：`/opt/fivemins/db_backup/{cron.log,backup.log}`

### 恢复

```bash
python3 /opt/fivemins/tools/db_restore.py --list        # 列出备份
python3 /opt/fivemins/tools/db_restore.py --latest      # 恢复最新（自动停/启容器）
python3 /opt/fivemins/tools/db_restore.py --file auth_20261012_0900.sqlite
```

## 六、日常运维

> 本机 Docker Compose 是 **v2 独立二进制**（`/usr/local/bin/docker-compose`），命令形如 `docker-compose ...`；
> **没有** `docker compose` 插件形式，写别的形式会报 `unknown shorthand flag`。

| 任务 | 命令 |
|---|---|
| 状态 | `sudo docker ps`；健康 `curl localhost:5000/api/health` |
| 看日志 | `sudo docker exec fivemins-portal tail -50 /app/application/portal/logs/portal.log`（另有 all_in_one/stats/usg_virus_test/fastip_report/supervisord .log） |
| 重启单应用 | 容器内 `supervisorctl restart all_in_one`（socket 在 `/tmp/supervisord.sock`，需 `-c` 或默认配置） |
| 重建生产 | `cd /opt/fivemins && sudo docker-compose up -d --build` |
| 重建测试 | `sudo docker-compose -f docker-compose.test.yml up -d --build` |
| 改用户模板 | 走 5000「我来定模板」页面（推荐）；批量同步用 `docker cp` 到卷内 `editor_defaults/` |
| 更新公告栏 | 编辑 `data/whatsnew/updates.json`（容器卷），页面即改即生效 |
| 桌面版 exe 重建 | 见 `docs/REBUILD_EXE.md`（wine 工具链） |

## 七、发布流程（改动 → 生产）

```bash
cd /opt/fivemins

# 1) 改代码/配置（先改仓库文件）
# 2) 测试环境验证
sudo docker-compose -f docker-compose.test.yml up -d --build
sleep 15
cd application/test && YUCS_PASSWORD=yucs123 python3 -m pytest blackbox_8000/ -q   # 86
cd ../.. && python3 -m pytest application/test/all_in_one -q                        # 147
sudo docker cp "/opt/fivemins/application/test" fivemins-portal-test:/app/application/test
sudo docker exec fivemins-portal-test sh -c 'cd "/app/application/test/all_in_one" && python3 comprehensive.py'  # 280

# 3) 重建生产
sudo docker-compose up -d --build
curl localhost:5000/api/health   # {"ok":true,"status":"healthy"}

# 回滚：git checkout <上一个正常提交> && sudo docker-compose up -d --build
```

## 八、测试体系

| 套件 | 数量 | 运行位置 | 说明 |
|---|---|---|---|
| comprehensive | 280 | 容器内 in-process | 全场景生成回归（先 `docker cp` 测试目录） |
| blackbox_8000 | 86（含 28 项多用户并发） | 宿主 → 8000 容器 | 纯 HTTP 黑箱；容器不在时自动跳过 |
| pytest all_in_one | 147（+17 浏览器用例自动跳过） | 仓库根 | `pytest application/test/all_in_one -q` |

**CI（GitHub Actions）**：2026-10-12 修复（历史 58 次运行全部失败——根因：CI 无 playwright 且 `--ignore` 路径失效导致收集崩溃）。修复内容：
① workflow 改为**从仓库根**运行 `pytest application/test`（使 pytest.ini 忽略路径生效）；
② 需要浏览器的用例在缺失依赖时**自动跳过**（conftest hook + importorskip）；
③ blackbox/portal 用例在 8000 容器未运行时自动跳过。
本地模拟 CI 命令：

```bash
mkdir -p /tmp/no_pw/playwright && echo 'raise ModuleNotFoundError("no playwright")' > /tmp/no_pw/playwright/__init__.py
PYTHONPATH=/tmp/no_pw TEST_MODE=1 NO_BROWSER=1 BLACKBOX_BASE=http://127.0.0.1:9 \
  python3 -m pytest -q application/test          # 期望：0 failed / 0 error
```

## 九、GitHub 与网络

- 仓库：`https://github.com/yucongshen2021-spec/5mins-less-for-you-cloud`（public）
- **push 网络修复**：GitHub IP 会漂移。当前可用 IP 写在 `/etc/hosts`（2026-10-12 为 `20.27.177.113`）。
  失效时探测并更新（命令见 `docs/AGENTS.md`「Git Push 网络问题」段）。
- SSH 部署密钥：`~/.ssh/id_ed25519`（pubkey 备份在交接记录）——需在 GitHub 仓库 Settings → Deploy keys
  添加并勾选 write access 后方可 `git push git@github.com:...`。
- 2026-10-12 状态：本地领先 origin/main 若干提交（含本次清理），待推送通道就绪后推送。

## 十、已知问题与决策记录（2026-10-12）

| # | 事项 | 结论 |
|---|---|---|
| 1 | 生产 SECRET_KEY 为 `change-me-in-production` | **用户决策：保持不修改**。风险自评：内网工具、会话仅影响登录态；如需轮换按第三节操作 |
| 2 | 首页版本号 | 已从桌面版号 1.2.3 更新为 **2.0.0**（`RELEASE_INFO.json`，Web 版本号） |
| 3 | 停用应用 5001/5002/5004 | **保留源码** + supervisord 注释（恢复：取消注释并重建；域名抓取另需装 playwright + Chromium） |
| 4 | ER FastIP 5.0 变体、AR SD-WAN 页签 | 前端**「测试中」禁用**（验收完成后再开放） |
| 5 | 遗留保留物 | `src/all_in_one_v2.py` + `src/_templates.json`（桌面版聚合器及模板缓存，Web 端不加载）；`自动做测试报告 - cc/log/2099*`（test_report 测试运行目录）；`.wine64`/`.build_cache`（exe 重建工具链，勿删） |
| 6 | 清理归档 | 11 个未用模板目录等已移入 `.archive/orphans-20261012/`（30 天冷静期，`MANIFEST.md` 有完整清单与还原说明）；备份包在 `.archive/backup-20261012/` |

## 十一、本次清理记录（2026-10-12）

| 文件 | 内容 |
|---|---|
| `docs/CLEANUP_PLAN.md` | 清理整改完整方案（问题清单 P1-P4 + 批次 + 安全协议 + 决策） |
| `docs/CLEANUP_REPORT.md` | 实施结果报告（改了什么 / 归档了什么 / 验证数据 / 如何还原） |
| `log/2026-10-12-cleanup.md` | 逐批改动留痕 |
| `.archive/orphans-20261012/MANIFEST.md` | 归档清单 + 证据（safe_key 映射、引用扫描、内容对比） |
| `HISTORY.md` | 上线全纪录（10-12 条目含 CI 修复里程碑） |
