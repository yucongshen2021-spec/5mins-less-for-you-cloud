# 全量测试标准

> **目标：** 每次修改代码后，通过两层测试确保质量——代码逻辑层验证底层正确性，用户行为层验证真实使用体验。全量覆盖所有应用、所有场景、所有版本、所有功能和所有交互。
>
> **适用人员：** 本文件用于 Agent 自动执行测试。每个测试项应可独立运行、可复现、有明确通过条件。

---

## 目录

1. [测试架构](#1-测试架构)
2. [测试矩阵](#2-测试矩阵)
3. [Part 1: 代码逻辑测试](#3-part-1-代码逻辑测试)
4. [Part 2: Playwright 用户行为测试](#4-part-2-playwright-用户行为测试)
5. [测试数据](#5-测试数据)
6. [测试环境与执行](#6-测试环境与执行)

---

## 1. 测试架构

```
application/test/
├── _smoke_helpers.py          # Portal + 子应用 smoke test 共享工具
├── all_in_one/                # 配置生成 — 全量覆盖率最高的应用
│   ├── _bootstrap.py          # 环境初始化
│   ├── common.py              # 共享夹具
│   ├── conftest.py            # pytest fixtures
│   ├── test_apis.py           # API 端点测试
│   ├── test_business.py       # 业务逻辑测试
│   ├── test_generation.py     # 生成结果正确性测试
│   ├── test_templates.py      # 模板系统测试
│   ├── test_params.py         # 参数处理测试
│   ├── test_e2e.py            # Flask test client E2E
│   ├── test_e2e_playwright.py # Playwright 全功能 E2E
│   ├── test_template_editor_e2e.py  # 模板编辑器 E2E
│   ├── test_hostname_all.py   # Hostname 全场景测试
│   ├── test_mpls_bypass.py    # MPLS bypass 路由测试
│   ├── test_usg_return_routes.py    # USG 回程路由测试
│   ├── test_er5_ipsec.py      # ER 5.0 IPSec 测试
│   ├── test_er5_ipsec_api.py  # ER 5.0 IPSec API 测试
│   ├── test_er5_ipsec_content.py    # ER 5.0 IPSec 内容测试
│   ├── comprehensive.py       # 全量回归脚本
│   ├── compare.py             # 配置差异对比工具
│   └── audit_templates.py     # 模板审计工具
├── config_analyzer/           # 配置梳理
│   └── test_smoke.py          # Smoke test
├── domain_capture/            # 域名抓取
│   └── test_smoke.py          # Smoke test
├── test_report/               # 测试报告
│   └── test_smoke.py          # Smoke test
└── portal/                    # Portal 总控
    └── test_smoke.py          # Smoke test
```

### 命名规范

| 类型 | 文件命名 | 示例 |
|------|---------|------|
| API 测试 | `test_apis.py` | `test_apis.py` |
| 业务逻辑 | `test_business.py` | `test_business.py` |
| 生成正确性 | `test_generation.py` | `test_generation.py` |
| E2E (Flask client) | `test_e2e.py` | `test_e2e.py` |
| E2E (Playwright) | `test_e2e_playwright.py` | `test_e2e_playwright.py` |
| 专项功能 | `test_<feature>.py` | `test_hostname_all.py` |
| Smoke test | `test_smoke.py` | `test_smoke.py` |

---

## 2. 测试矩阵

### 2.1 应用 × 测试类型

| 应用 | 代码逻辑测试 | Playwright E2E | 最低通过率 |
|------|:-----------:|:-------------:|:--------:|
| 配置生成 (all_in_one) | 107+ cases | 40+ cases | 100% |
| 测试报告 (test_report) | 5+ cases | 8+ cases | 100% |
| 域名抓取 (domain_capture) | 3+ cases | 6+ cases | 100% |
| 配置梳理 (config_analyzer) | 3+ cases | 10+ cases | 100% |
| Portal 总控 | 5+ cases | 12+ cases | 100% |

### 2.2 配置生成 — 场景 × 版本矩阵

全量场景矩阵（含 SCENARIOS dict 22 个基础场景 + 5.0 版本叠加 + IPSec 子变体）：

| 工具 | 场景 | 4.0 | 5.0 OpenVPN | 5.0 IPSec |
|------|------|:--:|:----------:|:--------:|
| **Epoch FastIP** | HK 香港出口 | ✓ | ✓ | ✓ |
| | 非香港出口 (US) | ✓ | ✓ | ✓ |
| | ER 飞连 (Flink) | ✓ | ✓ | n/a |
| | ER 新增出口 (New Exit) | ✓ | ✓ | n/a |
| | ER 域名分流 (Domain Split) | ✓ | ✓ * | n/a |
| **USG FastIP** | 非香港出口 (US) | ✓ | — | — |
| | HK 香港出口 | ✓ | — | — |
| | 飞连 (Flink) | ✓ | — | — |
| | 新增出口 (New Exit) | ✓ | — | — |
| **Epoch MPLS** | 国内配置 | ✓ | — | — |
| | IPSec | ✓ | — | — |
| | 海外配置 | ✓ | — | — |
| **AR SD-WAN** | 单机单WAN · OPS | ✓ | — | — |
| | 单机单WAN · Factory | ✓ | — | — |
| | 单机双WAN · OPS | ✓ | — | — |
| | 单机双WAN · Factory | ✓ | — | — |
| | 双机主 OPS | ✓ | — | — |
| | 双机备 OPS | ✓ | — | — |
| | 双机主 Factory | ✓ | — | — |
| | 双机备 Factory | ✓ | — | — |

> \* 域名分流 5.0 在 `/api/tools` 中标记为 `unimplemented`
>
> **总计需验证: 7 ER 4.0 + 7 ER 5.0 + 4 USG + 3 MPLS + 8 AR = 29+ 场景-版本组合，含 IPSec 子变体超过 35+ 生成端点测试**

### 2.2.1 生成 API 端点（每个需独立测试）

| API 端点 | 覆盖范围 | 关键参数 |
|----------|---------|---------|
| `/api/generate/epoch_fastip` | ER 4.0 全部 5 变体 | `variant`, `data_header`, `network` |
| `/api/generate/epoch_fastip5` | ER 5.0 全部 6 变体(含 IPSec) | `variant`, `tunnel_type`, `data_header`, `network` |
| `/api/generate/usg_fastip` | USG 全部 4 变体 | `variant`, `data_header`, `network` |
| `/api/generate/epoch_mpls` | MPLS 全部 3 变体 | `variant`, `data_header`, `network` |
| `/api/generate/ar_sdwan` | AR 8 变体(返回 ops+factory) | `variant`, `data_header`, `network` |

### 2.3 Portal — 功能矩阵

| 功能 | Demo (500x) | Release (700x) |
|------|:----------:|:-------------:|
| 导航切换（4 个应用） | ✓ | ✓ |
| 侧栏收起/展开 | ✓ | ✓ |
| 帮助面板 | ✓ | ✓ |
| 更新检查 | ✓ | ✓ |
| 在线升级 | — | ✓ |
| 下载完整应用 | ✓ | — |
| 子应用健康检查 | ✓ | ✓ |
| 子应用代理 | ✓ | ✓ |

### 2.4 当前测试缺口（优先级排序）

Explorer agent 对现有 `application/test/` 目录的分析：

| 应用 | 现有测试 | 缺失测试 |
|------|---------|---------|
| **all_in_one** | 107+ cases 覆盖生成/模板/参数/API/IPSec/Playwright | 基本完整 |
| **test_report** | 仅 1 个 smoke test (HTTP 200) | `/api/run`, `/api/stop`, `/api/logs` SSE, `/api/download`, 任务生命周期, 并发, CE 预设 |
| **domain_capture** | 仅 1 个 smoke test (HTTP 200) | `/api/capture` 真实抓取, CNAME 解析, IP 过滤, 浏览器检测, 超时, 错误处理, 导出 |
| **config_analyzer** | 仅 2 个 smoke tests | NAT 解析, 拓扑 SVG, 映射解析, CSV 导出, 文件导入, ER/USG 切换, 缩放, 边界情况 |
| **portal** | 7 个 smoke tests | 代理完整路径, 子应用重启, 健康检查刷新, 并发代理 |

> **优先级 P0:** test_report、domain_capture、config_analyzer 缺少代码逻辑测试 — 当前只有 HTTP 200 检查。
> **优先级 P1:** 所有应用的 Playwright E2E 测试需要补充。

---

## 3. Part 1: 代码逻辑测试

代码逻辑测试从底层代码出发，**不依赖浏览器**。使用 `pytest` + Flask test client（无需启动真实服务器）。

### 3.1 配置生成 (all_in_one) — 107+ cases

#### T1: API 端点测试 (`test_apis.py`)

每个 API 端点必须验证：200 响应、正确 Content-Type、返回数据非空且格式正确。

```
端点                                        测试点
──────────────────────────────────────────────────────────
GET  /api/tools                              返回 4 个工具列表
GET  /api/scenarios                          返回 22+ 场景列表
GET  /api/examples/<tool>/<variant>          每种 tool+variant 返回有效示例
GET  /api/notes/<tool>?variant=<variant>     每种 tool+variant 返回有效备注
GET  /api/sponsor-board                      返回感谢名单
POST /api/generate/epoch_fastip              有效输入 → 200 + 配置文本非空
POST /api/generate/epoch_fastip5             有效输入 → 200 + 5.0 语法
POST /api/generate/usg_fastip                有效输入 → 200 + USG 语法
POST /api/generate/epoch_mpls                有效输入 → 200 + MPLS 语法
POST /api/generate/ar_sdwan                  有效输入 → 200 + AR 语法
POST /api/template/load                      有效 key → 返回模板内容
POST /api/template/save                      有效数据 → 200
POST /api/template/reset                     有效 key → 模板恢复出厂
POST /api/template/preview                   有效模板 → 返回预览配置
POST /api/init-defaults                      获取默认值列表
POST /api/init-defaults/save                 保存默认值 → 200
POST /api/init-defaults/reset                重置默认值 → 200
GET  /api/init-defaults/<scenario_key>       获取特定场景默认值
```

**通过条件：** 所有端点返回正确响应码和有效数据。

#### T2: 生成正确性测试 (`test_generation.py`)

每个场景 × 每个版本：
- 给定标准示例数据 → 调用 `/api/generate/<tool>` → 验证输出包含关键配置行
- 关键配置行检查项（以 Epoch FastIP HK 为例）：
  - `host-name` 行存在
  - WAN/LAN 接口配置存在
  - `protocols bgp` 段存在
  - `set protocols static route` 行数量 > 0

**通过条件：** 28+ 场景-版本组合全部生成有效配置。

#### T3: 业务逻辑测试 (`test_business.py`)

```
测试点                                        验证内容
────────────────────────────────────────────────────────
Hostname 提取                                 从数据头正确提取 hostname
DHCP 模式                                    勾选 DHCP → 不生成 WAN 静态 IP
旁挂模式                                     勾选旁挂 → 不生成 LAN 接口
回程路由生成                                 勾选回程路由 → 配置包含 return route
WAN/LAN 接口号                               接口号参数正确传递
BGP 配置                                     多 PE 的 BGP neighbor 正确生成
NAT 规则                                     源 NAT 规则正确生成
内网段路由                                   内网段黑洞路由生成
域名分流                                     域名组配置正确生成
MPLS bypass 路由                             黑洞 → 下一跳链路正确
USG 回程路由                                 回程路由 → NAT 策略对应
ER 5.0 IPSec 隧道类型                        IPSec 选中 → 生成 IPSec 配置而非 OpenVPN
ER 5.0 新语法                                set 语句格式符合 5.0 规范
```

**通过条件：** 每个测试用例有明确断言，不依赖模糊判断。

#### T4: 模板系统测试 (`test_templates.py`)

```
测试点                                        验证内容
────────────────────────────────────────────────────────
模板加载                                     有效 key → 返回模板文本
模板保存                                     保存新内容 → 再次加载验证一致性
模板重置                                     重置后 → 内容恢复出厂默认
模板预览                                     预览请求 → 返回预览生成的配置
模板热更新                                   保存后 → 生成配置反映新模板
跨场景隔离                                   场景 A 的模板修改不影响场景 B
模板版本计数器                               每次保存递增
```

**通过条件：** 所有模板 CRUD 操作正确，跨场景无污染。

#### T5: 参数处理测试 (`test_params.py`)

```
测试点                                        验证内容
────────────────────────────────────────────────────────
空输入处理                                   空参数 → 返回错误提示，不崩溃
缺失必填字段                                 缺失 LineID → 错误提示
特殊字符                                     参数含 / \ : * ? " < > | → 正确处理
超长输入                                     参数 > 1000 字符 → 不崩溃
Unicode 输入                                 中文、emoji → 正确处理
多出口 IP 解析                               多种分隔符 → 提取所有 IP
```

**通过条件：** 所有边界情况和非法输入都不会导致 500 错误。

#### T6: ER 5.0 IPSec 专项 (`test_er5_ipsec*.py`)

```
测试文件                                      验证内容
────────────────────────────────────────────────────────
test_er5_ipsec.py                             IPSec 模板完整性
test_er5_ipsec_api.py                         IPSec 场景 API 正确响应
test_er5_ipsec_content.py                     IPSec 生成内容逐项检查
test_er5/test_hk_generation.py                HK IPSec 生成验证
test_er5/test_flink_generation.py             Flink IPSec 生成验证
```

**通过条件：** IPSec 场景的 VPN 类型、IKE 参数、IPSec 参数、隧道接口全部正确。

### 3.2 测试报告 (test_report) — 8+ cases

**当前状态：** 仅 1 个 smoke test (HTTP 200)。需大幅扩充。

```
测试文件: test/test_report/test_api.py (新建)
──────────────────────────────────────────────────

T1  GET  /                         页面返回 (200)，HTML 含「测试报告」标题
T2  POST /api/run                  有效参数 → 返回 {"task_id": "...", "status": "started"}
                                    参数: test_date, line_id, customer, bandwidth, engineer,
                                    ce_host, ce_port, ce_user, ce_password,
                                    main_ip, backup_ip, local_site, accel_site,
                                    product_type, ce_ping_interval_i, ce_ping_interval_m
T3  POST /api/run                  缺失必填字段 → 返回错误，不崩溃
T4  GET  /api/logs/<task_id>       SSE 流 → 包含进度日志行
T5  GET  /api/logs/<invalid>       无效 task_id → 返回适当错误
T6  POST /api/stop                 发送 {task_id} → 任务标记停止
T7  POST /api/stop                 不存在的 task_id → 不崩溃
T8  GET  /api/download/<filename>  任务完成后 → 下载 .docx 文件
```

### 3.3 域名抓取 (domain_capture) — 8+ cases

**当前状态：** 仅 1 个 smoke test (HTTP 200)。需大幅扩充。

```
测试文件: test/domain_capture/test_api.py (新建)
──────────────────────────────────────────────────

D1  GET  /                         页面返回 (200)，HTML 含「域名抓取」及 textarea
D2  POST /api/capture              URL="https://example.com" → 返回域名列表 (非空)
                                    参数: url, timeout(5-120s), wait(0-30s),
                                    include_ip(bool), resolve_dns(bool)
D3  POST /api/capture              resolve_dns=true → 返回含 CNAME 链路数据
D4  POST /api/capture              include_ip=true → 结果含 IP 地址条目
D5  POST /api/capture              无效 URL (如 "not-a-url") → 返回错误，不崩溃
D6  POST /api/capture              超时 URL → timeout 参数生效，不无限等待
D7  POST /api/capture              空 URL → 返回验证错误
D8  POST /api/capture              长超时(120s) → 正确处理
```

### 3.4 配置梳理 (config_analyzer) — 12+ cases

**当前状态：** 仅 2 个 smoke tests (HTML 200 + DOM 元素检查)。需大幅扩充。

```
测试文件: test/config_analyzer/test_analyzer.py (新建)
────────────────────────────────────────────────────

CA1  GET  /                            HTML 返回 (200)，含 scene-tabs + configText textarea
CA2  ER 解析 — 基本 NAT               粘贴标准 ER 配置 → 调用 parseERConfig()
                                        → NAT 表非空，含 source/destination/translation
CA3  ER 解析 — 静态路由                解析含静态路由的配置 → 路由表含 next-hop 链
CA4  ER 解析 — BGP 路由                解析含 BGP 配置 → BGP 邻居正确识别
CA5  USG 切换                          点击 USG tab → 解析模式切换为 USG
CA6  USG 解析 — 防火墙规则             粘贴 USG 配置 → 解析出策略路由
CA7  映射解析 — 5 种格式               "-", "=", ":", "->" 分隔符全部正确解析
                                        + 分号换行符作为分隔
CA8  拓扑 SVG 渲染                     解析后 → #topoSvg 包含 SVG 元素
CA9  CSV 导出                          点击导出 → 生成的 CSV 格式正确
CA10 文件导入                          加载 .txt 文件 → 内容填入 configText
CA11 缩放控制                          点击 +/- → SVG 缩放变化
CA12 空配置处理                        空 configText → 解析返回空结果，不崩溃
CA13 畸形配置处理                      无效配置文本 → 优雅降级，不崩溃
```

### 3.5 Portal 总控 — 5+ cases

```
测试点                                        验证内容
────────────────────────────────────────────────────────
GET  /                                        首页返回 (200)，含 4 个 nav-item
GET  /api/status                              返回 4 个子应用状态，字段完整
POST /api/update/check                        返回 status 字段
Proxy 路由                                    /app/<id>/ 代理到对应子应用
子应用离线处理                                子应用未启动 → status 返回 reachable=false
```

---

## 4. Part 2: Playwright 用户行为测试

Playwright 测试模拟真实用户在浏览器中的操作。必须使用 `mcp__plugin_playwright_playwright` 工具逐项验证。

### 测试原则

1. **真实浏览器** — 使用 Playwright 启动 Chromium，不 mock 任何浏览器行为
2. **完整操作路径** — 从页面加载到结果验证，模拟用户完整操作流程
3. **视觉验证** — 元素可见、文字未被遮盖、按钮可点击、颜色/间距符合 DESIGN.md
4. **交互验证** — 每个按钮点击有反馈、每个输入框接受输入、每个选择生效
5. **API 测试全绿 ≠ 用户能正常使用** — 必须浏览器验证

### 4.1 Portal 总控 — 12 项检查

```
P1  页面加载         打开 http://localhost:5000 (demo) 或 :7000 (release)
                      → 标题="帮你节省5分钟"
                      → 品牌名、版本号正确显示
                      → 4 个应用导航项全部渲染

P2  导航切换         依次点击每个应用 → iframe 加载对应页面
                      → Banner 更新为应用名
                      → 导航项 active 状态切换

P3  侧栏收起         点击 ☰ → 侧栏消失
                      → 再次点击 → 侧栏恢复

P4  帮助面板         点击 ? → 帮助面板弹出
                      → 内容包含 4 个工具的说明
                      → 点击 × 或遮罩 → 关闭

P5  在线状态         检查每个导航项的圆点颜色
                      → 子应用在线 = 绿色
                      → 子应用离线 = 红色

P6  自动激活         页面加载后 → 第一个 online 应用自动激活
                      → iframe 显示对应应用内容

P7  下载入口         (demo 版) 左下角显示「下载完整应用」
                      → 按钮包含版本号和文件大小

P8  更新检查按钮     (demo 版) 点击 ⟔ 按钮
                      → 按钮显示 loading 状态
                      → 返回结果后显示 toast

P9  版本标签         demo 版显示「DEMO」橙色标签
                      release 版显示「RELEASE」绿色标签

P10 Live 指示器      Live 圆点呼吸动画正常

P11 刷新健康检查     等待 10 秒 → 状态自动刷新

P12 控制台错误       加载页面 → 控制台无 JS 错误（favicon 404 除外）
```

### 4.2 配置生成 (all_in_one) — 40+ 项检查

#### 4.2.1 导航与场景选择

```
A1  工具导航标签     点击 Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN
                      → 每个标签激活后显示对应场景

A2  感谢页           点击「感谢」→ 显示贡献者列表

A3  模板编辑器入口    点击「我来定模板」→ cascade menu 正确渲染
                      → 一级菜单 4 项全部显示
                      → hover 展开二级/三级菜单
                      → 点击叶子节点 → 加载对应模板

A4  版本切换         选择 ER/USG 场景 → 点击 4.0 / 5.0
                      → 参数面板根据版本变化
                      → (5.0) 隧道类型按钮出现

A5  场景变体切换     点击场景变体按钮（HK/非HK/飞连/新增出口/域名分流）
                      → 备注说明更新
                      → 填写示例更新
                      → 参数面板更新
```

#### 4.2.2 参数设置与交互

```
A6  数据头输入       在数据头 textarea 粘贴有效数据
                      → Hostname 自动提取到参数栏
                      → 其他参数（WAN IP、CE LOIP 等）根据 map 映射自动填充

A7  清除数据头       点击「清除数据头」
                      → textarea 清空

A8  Hostname 手动输入 在 Hostname 文本框输入 → 接受输入

A9  WAN 接口号       修改接口号 → 值正确更新

A10 WAN DHCP 勾选   勾选 DHCP → WAN IP/网关输入框可能隐藏/禁用

A11 LAN DHCP 勾选   勾选/取消 DHCP → 相应输入框状态变化

A12 回程路由勾选     勾选/取消 → 状态切换

A13 旁挂模式勾选     勾选 → LAN 接口相关参数隐藏
```

#### 4.2.3 生成与输出

```
A14 生成配置         填写数据头 + 参数 → 点击「生成配置」
                      → 输出区显示配置文本
                      → 配置文本非空
                      → 配置文本含关键命令（host-name / set protocols 等）

A15 复制输出         点击「复制输出」→ 配置复制到剪贴板
                      → Toast 提示「已复制」

A16 导出脚本         点击「导出脚本」→ 触发文件下载

A17 Ctrl+Enter       聚焦任意输入框 → Ctrl+Enter → 触发生成配置

A18 生成结果可编辑    输出区 textarea 可手动编辑
```

#### 4.2.4 模板编辑器

```
A19 场景树渲染       Cascade menu 所有层级展开无遮挡
                      → 叶子节点文字完整可见

A20 加载模板         点击场景叶子 → 模板编辑器加载对应模板
                      → 模板内容非空

A21 编辑模板         修改模板内容 → 内容正常编辑

A22 保存模板         修改后点击保存 → 成功 toast

A23 预览模板         点击预览 → 预览区显示生成的配置

A24 重置模板         点击重置 → 模板恢复出厂内容

A25 跨场景隔离      场景 A 修改模板 → 切换到场景 B
                      → 场景 A 的修改不影响场景 B

A26 模板热更新       修改模板 → 保存 → 主页面生成配置反映新模板
```

#### 4.2.5 全场景遍历

```
A27 HK 香港出口 4.0   选择 Epoch FastIP → 4.0 → HK → 填示例 → 生成 → 验证输出

A28 HK 香港出口 5.0 OpenVPN  同上 but 5.0 → 验证 5.0 语法

A29 HK 香港出口 5.0 IPSec    5.0 → 选 IPSec → 验证 IPSec 配置

A30 非香港出口 4.0   选择 US variant → 填示例 → 生成 → 验证输出

A31 非香港出口 5.0 OpenVPN

A32 非香港出口 5.0 IPSec

A33 ER 飞连 4.0      选择 Flink → 填示例 → 生成 → 验证输出

A34 ER 飞连 5.0

A35 ER 新增出口 4.0   选择 New Exit → 填示例 → 生成

A36 ER 新增出口 5.0

A37 ER 域名分流 4.0   选择 Domain Split → 填示例 → 生成

A38 ER 域名分流 5.0

A39-A42 USG FastIP   4 个变体 × 两个版本 → 验证生成

A43-A45 Epoch MPLS   国内 / IPSec / 海外 → 验证生成

A46-A53 AR SD-WAN    8 个变体 → 验证生成
```

#### 4.2.6 UI 合规

```
A54 字体一致性       检查 font-family 为 Inter（非 DM Sans）
                      → 参见 DESIGN.md typography

A55 颜色一致性       Primary 按钮色为 #f54e00
                      → 背景为 #f7f7f4 (canvas)
                      → 参见 DESIGN.md colors

A56 无文字遮盖       所有 label、按钮文字完整可见
                      → 无 overflow:hidden 截断

A57 无布局溢出       所有元素在视口内
                      → 无横向滚动条（除必要情况）

A58 控制台无错误      操作全流程 → console 无 JS 错误
```

### 4.3 测试报告 (test_report) — 8 项检查

```
T1  页面加载         打开测试报告应用 → 页面正常渲染

T2  表单控件         所有输入框、按钮可见且可交互

T3  开始测试         填写参数 → 点击开始测试
                      → 日志区实时显示进度

T4  停止测试         测试运行中 → 点击停止 → 测试终止

T5  下载报告         测试完成后 → 下载按钮可用
                      → 点击下载 → 获取 .docx 文件

T6  错误处理         参数缺失 → 点击开始 → 显示错误提示

T7  无文字遮盖       所有 UI 文字完整可见

T8  控制台无错误      操作全流程 → 无 JS 错误
```

### 4.4 域名抓取 (domain_capture) — 6 项检查

```
D1  页面加载         打开域名抓取应用 → 页面正常渲染

D2  URL 输入         在输入框输入网址 → 接受输入

D3  开始抓取         输入有效 URL → 点击抓取
                      → 显示加载状态
                      → 结果区显示域名列表

D4  CNAME 链路       结果中包含 CNAME 链路信息

D5  CDN 识别         结果中包含 CDN 归属标签

D6  错误处理         输入无效 URL → 点击抓取 → 显示错误提示，不崩溃
```

### 4.5 配置梳理 (config_analyzer) — 10 项检查

```
C1  页面加载         打开配置梳理应用 → 页面正常渲染
                      → 标题="ER/USG Config Analyzer"

C2  ER 标签页        默认显示 ER 标签 → ER 相关控件可见

C3  USG 切换         点击 USG 标签 → 切换到 USG 模式

C4  配置粘贴         在 textarea 粘贴 VyOS 配置文本 → 接受输入

C5  解析并梳理       粘贴配置 → 点击「解析并梳理」
                      → 拓扑图画布显示结果

C6  主线显示         解析结果中主线正确标记

C7  备线显示         备线正确标记

C8  未知线路          未知类型线路正确标记

C9  隧道配色          不同隧道类型使用不同颜色

C10 SNAT/默认路由    摘要区显示 SNAT 网段和默认路由
```

### 4.6 跨应用综合测试

```
X1  多应用并发       同时打开 4 个应用 → 在 iframe 中各自正常运行

X2  应用切换记忆     从配置生成切换到配置梳理再切回
                      → 配置生成保持之前的状态（iframe 未销毁）

X3  浏览器后退       点击浏览器后退 → 页面状态保持

X4  Demo/Release 切换 分别启动 demo (500x) 和 release (700x)
                      → 两者功能一致（除版本特有功能外）
```

---

## 5. 测试数据

### 5.1 配置生成 — 标准测试数据

每个场景使用 `/api/examples/<tool>/<variant>` 返回的官方示例数据。

**快速调试数据头（Epoch FastIP HK）：**
```
MAIN lineid: 603642Ar3 主PE： szd-natflr2 WANIP: 10.40.25.188/30 TUNNEL: vtun40826 Docking：121.12.81.3 CE LOIP: 10.20.186.235 HKIP：10.60.241.250 --> 103.48.141.157 BGPSERVER IP： 10.10.99.168,10.10.99.169 BACKUP PE：szc-natbk10 WANIP: 10.41.25.188/30 TUNNEL: vtun50826 Docking： 120.133.129.72 CE LOIP: 10.20.186.235 HKIP：10.60.241.250 --> 103.48.141.157 BGPSERVER IP：10.10.99.198,10.10.99.199
```

### 5.2 配置梳理 — 标准测试配置

```vyos
set system host-name 'ER-GZ-ZM-01'
set interfaces ethernet eth0 address '10.40.25.190/30'
set interfaces ethernet eth0 description 'WAN-MAIN'
set interfaces ethernet eth5 address '192.168.5.1/24'
set interfaces ethernet eth5 description 'LAN'
set interfaces vtun vtun40826 address '10.20.186.235/30'
set interfaces vtun vtun40826 description 'TUNNEL-MAIN-szd-natflr2'
set protocols bgp 64512 neighbor 10.20.186.236 remote-as '64513'
set protocols static route 10.40.25.188/32 next-hop 10.30.1.1
set service nat source rule 100 outbound-interface 'eth0'
set service nat source rule 100 source address '192.168.0.0/16'
set service nat source rule 100 translation address 'masquerade'
```

### 5.3 域名抓取 — 标准测试 URL

```
https://www.baidu.com
https://www.example.com
```

---

## 6. 测试环境与执行

### 6.1 环境要求

| 组件 | Demo (500x) | Release (700x) |
|------|------------|---------------|
| Python | 系统 `py -3` | `runtime/python/python.exe` (3.13.13) |
| Portal 端口 | 5000 | 7000 |
| 配置生成端口 | 5003 | 7003 |
| 测试报告端口 | 5002 | 7002 |
| 域名抓取端口 | 5001 | 7001 |
| 配置梳理端口 | 5004 | 7004 |
| Playwright | 已安装 | 已安装 |

### 6.2 执行前检查

```powershell
# 1. 检查无残留进程
foreach ($p in @(5000..5004 + 7000..7004)) {
    netstat -ano | Select-String ":$p " | Select-String "LISTENING"
}

# 2. 清理 __pycache__
find . -type d -name __pycache__ -exec rm -rf {} +

# 3. 确认分支 & 未提交修改
git branch
git status --short
```

### 6.3 执行顺序

```
1. 代码逻辑测试     pytest application/test/                           ~90s
2. Portal 导航      Playwright → P1-P12                                ~60s
3. 配置生成 E2E     Playwright → A1-A58                                ~180s
4. 测试报告 E2E     Playwright → T1-T8                                 ~45s
5. 域名抓取 E2E     Playwright → D1-D6                                 ~30s
6. 配置梳理 E2E     Playwright → C1-C10                                ~30s
7. 跨应用综合       Playwright → X1-X4                                 ~30s
                                                          总计: ~7-8 分钟
```

### 6.4 每日回归检查清单

修改任何代码后，**最低限度**必须通过：

- [ ] pytest 全量（代码逻辑层无 regression）
- [ ] Portal 导航 4 个应用（每个 iframe 正确加载）
- [ ] 配置生成 — 至少 1 个场景走通完整流程（选场景 → 填参数 → 生成 → 验证输出）
- [ ] 控制台无 JS 错误（除 favicon 404）
- [ ] 无文字遮盖或布局溢出

### 6.5 发版前全量验证

构建 release 之前，必须通过 **全量测试矩阵**：

- [ ] pytest 全量：107+ cases 全部 PASS
- [ ] Playwright Demo (500x)：所有 P/A/T/D/C/X 检查项
- [ ] Playwright Release (700x)：P/A/T/D/C 检查项（release 特有功能）
- [ ] UI 合规：字体、颜色、间距符合 DESIGN.md
- [ ] 控制台零错误
- [ ] 构建后解压 zip → 端到端起 portal → 4 个子应用全部可访问
