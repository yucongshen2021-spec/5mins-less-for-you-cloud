# HISTORY · 上线全纪录

> **项目**：帮你节省5分钟 · 网络设备配置生成平台
> **上线日期**：2026-06-16（Linux/Docker 生产部署）
> **本文档**：完整记录上线以来的技术演进、架构变更、事故与修复，持续更新。
> **最后更新**：2026-10-12

---

## 〇、项目与上线概况

**一句话**：把网络工程师每次 5 分钟的「照抄配置」变成 30 秒的「粘贴数据头 → 一键出配置」。

- 覆盖设备：VyOS（ER 4.0 / 5.0）、华为 USG、AR 路由器（SD-WAN / 传统组网）、MPLS
- 上线时间：**2026-06-16**（从 Windows 桌面版迁移至 Linux/Docker，部署生产服务器）
- 首个用户：2026-06-18（yucs）
- 当前规模（2026-10-12）：**31 个场景**、**23 个注册用户**、**540+ 次配置生成**

### 服务与端口（当前）

| 服务 | 端口 | 说明 |
|---|---|---|
| Portal | 5000 | 统一入口、反向代理、登录鉴权、分权后台入口 |
| all_in_one（配置生成） | 5003 | gunicorn 16 worker 多进程并发 |
| USG 测病毒 | 5005 | 操作指引页 + 工具包下载 + 下载统计 |
| FASTIP 测试报告 | 5006 | 操作指引页 + 桌面版下载 |
| stats 看板 | 9000 | 统计仪表盘 + 管理后台 + 用户个人看板 |
| 80 端口连通性测试页 | 80 | 独立容器，与正式环境隔离（2026-10-09） |

测试环境：8000 → 5000、8001 → 9000。
已停用（代码保留）：域名抓取 5001、测试报告 5002、配置梳理 5004。

---

## 一、上线前夜（2026-04 ~ 06-15）· 背景简述

> 完整故事见 `docs/经历.md`，此处只速记。

- 2026-04~05：四个独立 tkinter 桌面工具（ER FastIP / USG FastIP / Epoch MPLS / AR SD-WAN），PyInstaller 打包 exe 交付客户
- 2026-05-21：开始 Web 化 —— Portal（Flask 外壳 + iframe 嵌子应用）建立
- 2026-05-28：测试体系整合（blackbox + comprehensive + pytest）
- 2026-05 ~ 06-15：Windows release 迭代（v1.0.0 → v1.2.3），自动更新 / 客户包 / 镜像机制
- 2026-06-15：v1.2.3 构建（RELEASE_INFO.json），最后一版桌面发布

---

## 二、上线与架构定型（2026-06-16 ~ 06-26）

### 06-16 · Linux/Docker 生产上线
- 迁移至 Linux/Docker 单容器部署，生产服务器启用
- make_report 引擎跨平台适配（Linux 命令）

### 06-17 · 架构日（最大一次架构改造）
- **tkinter 彻底移除**：业务模块原以 tkinter 写成，Web 下用 tkinter_stub 替代（不再需要 Xvfb / DISPLAY）
- **gunicorn 多进程并发**（首发 8 workers）：进程隔离解决 tkinter 非线程安全问题；配套多 worker 状态同步（mtime 轮询热重载，模板改动即时生效）
- **登录系统 + 用户 workspace 隔离**：`data/users/<uid>/editor_workspace/`，模板互不串号
- **访客模式**：未登录自动访客 session，敏感功能禁用
- **stats 用户追踪**：访问 / 生成记录落库，容量分析
- **supervisord 收敛**：只拉起在用应用（portal + all_in_one + stats）
- 多用户并发安全加固：generate 从磁盘读模板，避免全局状态串号

### 06-18 · 权限与并发
- 模板编辑器权限控制（初始限 yucs，后放宽为所有登录用户可编辑自己的模板）
- **gunicorn 8 → 16 workers**（16 = 最大并发请求数，4C4G 撑住）
- 16 用户并发测试（登录隔离 / 工作区隔离 / 并发生成 / 权限）
- 重置密码功能（旧密码验证）；yucs 首次部署自动创建（ADMIN_PASSWORD）
- stats 用户搜索；生成请求审计日志
- **Git Push 网络问题首次解决**：github.com 443 不通 → /etc/hosts 固定到可达 IP

### 06-19 ~ 06-26 · 稳定化
- 06-19：init-defaults 加载修复、MPLS inner_nets 同步
- 06-22：HK 解析器支持 LineID 格式数据头、US NAT 字段回退、测试报告 5 项修复
- 06-23：**分权后台系统**（5000 顶栏按钮 + 9000 用户看板 + 访客登录提示）；**全站时间统一 UTC+8**；后台只记录生成请求
- 06-25：session 有效期 24h → **30 天**
- 06-26：文档全面更新 + 迁移准备

---

## 三、功能爆发（2026-07）

### 07-02 ~ 07-03 · 访客权限收紧 + 预存 Bug 清理
- 访客禁用所有敏感功能（24 个按钮 HTML 层 disabled）：填写示例 / 备注 / 生成 / 复制 / 导出
- **Bug 1-5 修复**：editor_defaults tpl 与源码不同步、template/load 污染全局 ns、reset 改 ns、factory 快照为空、AR SD-WAN 与 MPLS IPSec 不读磁盘模板
- auth DB 时间修复（UTC → UTC+8）

### 07-08 · ER 单线支持
- ER 4.0 / 5.0 新增出口单线（无备线）支持 + 100.100 参数简化

### 07-13 · ⚠️ 数据删除事故 + 首批生产记录
- stats 现存最早生成记录（同日）
- **数据删除事故**：执行删除操作时误清用户数据（workspace + 访问记录）→ 确立「删除铁律」：
  8000 先模拟 → 列清单 → 二次确认 → 精准匹配，禁止通配符批量删除

### 07-17 · ER5 HK IPSec 场景
- 新增 ER 5.0 香港出口 IPSec 场景（GRE + IPSec 组合）
- 拨号 IP 路由改 1.1.1.1、192.168.55.250 NAT exclude 增加
- ER MPLS 海外主线 vtun_only 修复（模板写死的 GRE 段在 vtun_only 下产生残废行 `set interfaces tunnel  address '/30'`）

### 07-20 · 单出口 + 数据安全
- **ER 4.0 非香港出口单出口（无备线）配置支持**（+ 40 个测试用例）
- **数据库冗余备份方案**：每天 09:00 / 21:00 热备（sqlite3 backup API，不停服务），保留 14 天 + 每周一永久备份，备份后完整性校验
- ER5 HK IPSec 补全（DHCP / 回程路由 / 旁挂联动）
- 规则体系 v2.0：GLOBAL_RULES.md 建立；DESIGN.md 反向重写（以实际 UI 为真相来源）

### 07-21 ~ 07-22 · 智能检测
- whatsnew 告示栏上线（顶栏「最近更新」提示）
- **数据头贴错场景检测**：
  - HK 数据头贴 US 场景 / US 数据头贴 HK 场景 → 交叉误贴检测（硬阻断 + 提示）
  - USG 出口 IP 格式检测（条件 1 硬阻断 + 条件 2 提示）
- 「非香港出口 · 单出口」独立场景（「我来定模板」可单独定制）

### 07-23 · 配置修复批次
- RSVR2 路由策略 rule 100-400 补 `local-preference '50'`
- ER4 双出口 BGP 路由去重（备线块不再重复生成 BGP server 路由）
- ER5 SSH ACL 改用网络号 + OpenVPN adjust-mss
- 子应用登录链接被反代改写 404 修复 + 测试环境 stats 端口绑回本地

### 07-24 · USG 测病毒应用（5005）
- 新增独立应用：一键测 USG 安全功能（指引页 + 工具包下载 + 下载统计）
- 访客权限控制（未登录不可见关键信息、不可下载）
- portal 套 portal 修复（postMessage 顶层跳转方案，防 iframe sandbox 拦截）
- stats 搜索修复（支持按用户名搜索）

### 07-27 · FASTIP 测试报告应用（5006）+ wine 打包
- 新增独立应用：桌面版测试报告工具下载页
- **wine 跨平台打出真 Windows exe**（PyInstaller：report_gui.exe + make_report.exe）
- 生产 5000 部署（三应用在线：5003 / 5005 / 5006）

### 07-28 · Set-Cookie 会话覆盖修复
- 现象：刷新后需重新登录、点击记录详情 302 跳登录
- 根因：stats 子应用的 session cookie 与 portal 同名，反代透传后覆盖 portal 会话
- 修复：反代过滤子应用 Set-Cookie（portal 是唯一会话源）

---

## 四、配置质量攻坚（2026-08）

### 08 月上中旬 · ER 配置批量修复
> 对生成质量逐项验收，集中修复了一批 VyOS 语法 / 参数问题：

1. **注释数据头重复**：模板中备线注释硬编码 + `{bk_header_block}` 双重输出 → 删除硬编码段
2. **dummy 接口语法错误**：`set interface dummy`（单数、多余空格、tab 缩进）→ `set interfaces dummy dumXXX address 'x.x.x.x/32'`
3. **新增出口隧道 MSS 1300**（注意 4.0 与 5.0 语法不同）：
   - ER 4.0：`set firewall options interface {tun} adjust-mss '1300'`
   - ER 5.0：`set interfaces tunnel {tun} ip adjust-mss '1300'`
4. **DNS cache-size 1001 → 10000**：所有场景统一
5. **DNS recursion-desired**：所有场景 DNS 模块末尾统一补充
6. **默认路由统一**：`set protocols static route 0.0.0.0/0 next-hop 1.1.1.1 distance '222'`（所有含 DHCP 的场景，ER4/ER5 的静态与 DHCP 分支统一 222）

### 08-17 · USG 测试报告区分
- USG CE 测试项从与 ER 相同的 4 项 ping 改为：02 = 主线 tracert、03 = 备线 ping 1500、04 = 备线 tracert（与 ER 不同）
- 命令行白名单同步、报告模板描述按产品类型区分、新增 5 项断言测试

### 08-24 · 页签关闭
- ER FastIP 5.0 与 AR SD-WAN 全部页签关闭入口，显示「测试中」（未完成功能隐藏）

---

## 五、稳定运营（2026-09 ~ 10-12）

- **2026-09**：平稳运行（141 次生成记录），无重大变更
- **2026-10-09**：新增 **80 端口连通性测试页**（独立 Docker 容器，与正式环境完全隔离；仅静态页 + /health + /ip，用于网络连通性验证）
- **2026-10-12**：GitHub 仓库转为公开（yucongshen2021-spec/5mins-less-for-you-cloud）；本地提交整理入库；Git push 网络问题再次修复（GitHub IP 漂移 → 重新探测更新 /etc/hosts）；SSH 部署密钥生成（免 token 推送通道）
- **2026-10-12 · 系统级清理整改（交接版）**：全面校正文档/配置/表述（场景口径 29→31、测试口径 185→280、服务表补 5006 与 80 端口）；修复 db_backup 的 `-wal/-shm` 清理 bug（`Path.suffix` 永不命中，存量 56 个残留已清除）；**发现并修复 GitHub Actions 自上线以来 58 次运行全部失败**（根因：CI 无 playwright 致收集阶段崩溃 + `--ignore` 路径依赖仓库根未写明）——为浏览器/容器依赖用例补齐自动跳过守卫，本地 CI 等价模拟 184 passed / 116 skipped / 0 failed；11 个未用模板目录、8 个历史方案等移入 `.archive/`（三重验证 + MANIFEST）；「BY YUC」徽标与 Web 版本号 2.0.0 上线；新增 `docs/HANDOVER.md` 交接手册

---

## 六、架构演进专题（横向总结）

### 6.1 部署形态
Windows 桌面 exe → Web 门户（portal + iframe 子应用）→ Linux/Docker 单容器多进程

### 6.2 并发模型
单进程 → gunicorn 16 workers（进程隔离）+ tkinter_stub（去 GUI 依赖）+ 异步日志（deque + 后台线程批量落库，不阻塞请求）

### 6.3 鉴权与权限
- 登录 / 注册 / 重置密码三态切换，session 30 天
- 访客自动 session（所有敏感功能禁用，24 个按钮 HTML 层 disabled，不依赖 JS）
- 分权后台：yucs = 管理后台（9000/admin），普通用户 = 个人数据看板，访客 = 登录提示页
- test / ctest 开头账号不记日志

### 6.4 多用户数据隔离
每用户独立 workspace：`data/users/<uid>/editor_workspace/*.tpl`；出厂模板 + 用户模板双层结构，一键恢复出厂；访客使用共享 workspace

### 6.5 模板体系
- 每个场景 = 出厂模板（源码内）+ 磁盘模板（支持热更新）
- 「我来定模板」页面支持在线编辑、保存、预览、重置
- 修改即时生效（generate 从磁盘读模板，多 worker 通过 mtime 轮询同步）

### 6.6 反代与统一入口
Portal(5000) 反代 `/app/<id>/` → 子应用本地端口；HTML 属性 + JS 字符串路径重写；`<base>` 注入；Set-Cookie 过滤（保证 portal 是唯一会话源）

### 6.7 应用矩阵
all_in_one（配置生成）+ usg_virus_test + fastip_report + stats（看板），supervisord 统一进程管理；新增应用 = 独立目录 + 端口 + 注册（process_manager + supervisord）

### 6.8 数据与备份
SQLite（auth.sqlite + stats.sqlite）挂载 Docker 卷持久化；每日两次热备 + 完整性校验 + 14 天保留 + 周备份永久（tools/db_backup.py，cron 驱动）

---

## 七、基础设施与运维

### 服务器与容器
- 云服务器（Ubuntu 4C4G）+ Docker Compose 部署
- 容器：fivemins-portal（生产 5000/9000）、fivemins-portal-test（测试 8000/8001）、fivemins-port80-test（80 测试页，独立隔离）

### 测试体系（每次改动全量回归）
- comprehensive：280 项（全场景生成回归，含单出口 / 双出口 / SSH ACL / MSS / DNS 等断言）
- pytest（all_in_one）：147 项
- blackbox_8000：86 项（含 28 项多用户并发：登录隔离 / 工作区隔离 / 并发安全）
- 流程：跑全量 → 部署 8000 验证 → 同步 5000 生产

### Git 工作流
- 主仓库：github.com/yucongshen2021-spec/5mins-less-for-you-cloud
- Git push 网络修复：`/dev/tcp` 探测 GitHub 可用 IP → 写入 /etc/hosts（IP 会漂移，失效时重新探测）
- 2026-10-12：仓库转 public；生成 ed25519 SSH 部署密钥（免 token 推送通道）

---

## 八、事故与教训（重要）

1. **2026-07-13 数据删除事故**：误删用户数据 → 删除铁律（8000 模拟 → 清单确认 → 精准匹配，禁通配符）
2. **Set-Cookie 会话覆盖（07-28）**：子应用 cookie 覆盖 portal 会话 → 反代过滤 Set-Cookie
3. **全局 ns 污染（07-02）**：模板 load/reset 写全局命名空间 → 只读接口不做副作用
4. **时区混乱（06-23 / 07-03）**：SQLite 存 UTC、显示北京时间 → 全站统一 UTC+8
5. **GitHub 网络不稳定（多次）**：IP 漂移导致 push/fetch 失败 → hosts 固定可用 IP
6. **iframe sandbox 登录失效（07-24）**：sandbox 拦截顶层导航 → allow-top-navigation-by-user-activation + postMessage 双保险
7. **USG 单出口误判（07-22）**：单出口数据头被误判为 HK 格式 → 要求 2 个以上出口 IP 才判「同 IP」

> 更多踩坑记录：`log/mistake.txt`（68+ 条，持续累积）

---

## 九、运营数据（截至 2026-10-12）

| 指标 | 数值 |
|---|---|
| 注册用户 | 23 |
| 生成记录 | 540+（7 月 131 / 8 月 243 / 9 月 141 / 10 月 26） |
| 场景数 | 31（ER4 8 + ER5 7 + USG 4 + MPLS 3 + AR SD-WAN 8 + AR 传统 1） |
| 功能使用 Top5 | epoch_fastip(us) 181 · epoch_fastip(hk) 63 · epoch_fastip(new_exit) 49 · epoch_fastip(flink) 45 · usg_fastip(us) 36 |

---

> **维护约定**：上线后的重要变更（功能 / 架构 / 事故 / 基础设施）追加到对应章节；
> 重大事故记录「现象 → 根因 → 修复」三要素。日常细节见 `log/`，踩坑见 `log/mistake.txt`。
