# 项目治理文档 — 帮你节省5分钟

> **目标：** 本文档定义项目的完整功能、每个按钮的预期行为、以及对应的测试覆盖。以后所有测试必须按此文档执行，达到目标功能才可通过。
>
> **更新频率：** 每次功能变更时必须同步更新本文档。

---

## 目录

1. [项目概览](#1-项目概览)
2. [版本架构](#2-版本架构)
3. [Portal 总控 — 按钮功能 & 测试绑定](#3-portal-总控--按钮功能--测试绑定)
4. [配置生成 — 按钮功能 & 测试绑定](#4-配置生成--按钮功能--测试绑定)
5. [测试报告 — 按钮功能 & 测试绑定](#5-测试报告--按钮功能--测试绑定)
6. [域名抓取 — 按钮功能 & 测试绑定](#6-域名抓取--按钮功能--测试绑定)
7. [配置梳理 — 按钮功能 & 测试绑定](#7-配置梳理--按钮功能--测试绑定)
8. [更新模块 — 功能 & 测试绑定](#8-更新模块--功能--测试绑定)
9. [构建 & 发版](#9-构建--发版)
10. [测试工具索引](#10-测试工具索引)

---

## 1. 项目概览

### 1.1 项目定位

「帮你节省5分钟」是一个面向网络运维工程师的桌面工具箱，集成 4 个独立工具，通过统一 Portal 聚合访问。支持 Demo（试用）和 Release（正式交付）两个版本。

### 1.2 应用架构

```
Portal (Flask, port 5000/7000)
├── iframe ── 配置生成 (all_in_one - cc, port 5003/7003)
├── iframe ── 测试报告 (自动做测试报告 - cc, port 5002/7002)
├── iframe ── 域名抓取 (自动抓域名发2, port 5001/7001)
└── iframe ── 配置梳理 (自动梳理配置 - cc, port 5004/7004)

Mirror 服务 (tools/serve_mirror.py, port 8000)
  → 提供 manifest + zip 下载
  → Demo 版自动启动，Release 版需手动启动
```

### 1.3 技术栈

- **后端:** Python 3.13 + Flask
- **前端:** Vanilla HTML/CSS/JS（Inter 字体 + JetBrains Mono 代码）
- **测试:** pytest（逻辑）、Playwright（用户行为）
- **构建:** Python 脚本 `build_release.py` → zip 包
- **更新:** mirror 服务器 + update_check + upgrade 模块

---

## 2. 版本架构

| 属性 | Demo 版 | Release 版 |
|------|---------|------------|
| **端口** | 5000 (portal) + 5001-5004 | 7000 (portal) + 7001-7004 |
| **启动** | `py application/portal/app.py` | 解压 zip → 双击 `start_all.bat` |
| **RELEASE_MODE** | 不设置 | `RELEASE_MODE=1` |
| **标签** | 🟠 DEMO 橙色 | 🟢 RELEASE 绿色 |
| **侧栏底部** | 下载卡片 (dlCard) | 更新按钮 (upgradeBtn) + 手动检查 |
| **更新检查** | 无（按钮点击触发，无定时器） | 有（5 秒自动 + 每小时 + 手动按钮） |
| **更新横幅** | 无 | 有（橙色横幅 + 一键升级） |
| **下载入口** | `/api/download/latest` + `/download/latest.zip` | 无 |

### 2.1 版本识别规则

- **Demo:** `RELEASE_MODE` 环境变量不存在或为空
- **Release:** `RELEASE_MODE=1`
- **模板渲染:** `{% if is_release %}` 控制 UI 差异
- **JS:** `{% if is_release %}` / `{% if not is_release %}` 控制脚本差异

---

## 3. Portal 总控 — 按钮功能 & 测试绑定

### 3.1 页面加载

| 行为 | 预期结果 | 逻辑测试 | 用户测试 |
|------|---------|:------:|:------:|
| 打开 Portal 首页 | 标题="帮你节省5分钟"，品牌名正确显示 | `test_smoke.py:test_index` | P1 |
| 版本标签显示 | Demo: 🟠 DEMO 橙色标签；Release: 🟢 RELEASE 绿色标签 | — | P9 |
| 4 个导航项渲染 | 每个 nav-item 含 nav-dot + nav-label | `test_smoke.py:test_index_has_nav_items` | P1 |
| Live 指示器 | 绿色圆点 + "Live" 文字，呼吸动画 | — | P10 |
| 版本号显示 | `v<local_version>` + 版本描述文字 | `test_smoke.py:test_index_shows_version` | P1 |
| 自动激活第一个在线应用 | iframe 加载第一个 online 子应用 | — | P6 |
| 控制台零 JS 错误 | 除 favicon 404 外无错误 | — | P12 |

### 3.2 Header 区域

| 按钮 | 功能 | 预期结果 | 逻辑测试 | 用户测试 |
|------|------|---------|:------:|:------:|
| **☰ (toggleSidebar)** | 点击收起/展开左侧栏 | 侧栏滑出视图（collapsed class），☰ 保持可见。再次点击恢复。 | — | P3 |
| **? (toggleHelp)** | 点击弹出帮助面板 | 帮助面板 overlay 显示（visible class），内容含 4 个工具说明。点击 × 或遮罩关闭。 | — | P4 |

### 3.3 侧栏 — 导航切换

| 按钮 | 功能 | 预期结果 | 逻辑测试 | 用户测试 |
|------|------|---------|:------:|:------:|
| **nav-item × 4** | 点击切换子应用 | 被点击的 nav-item 添加 active class，Banner 更新为应用名，对应 iframe 显示（visible class）。其他 iframe 隐藏。 | `test_smoke.py:test_nav_items` | P2 |
| **nav-dot 状态** | 显示子应用在线状态 | 在线=绿色(success)，离线=红色(error)。10 秒自动刷新。 | `test_smoke.py:test_api_status` | P5 |

### 3.4 侧栏底部 — Demo 版（下载卡片）

| 按钮 | 功能 | 预期结果 | 逻辑测试 | 用户测试 |
|------|------|---------|:------:|:------:|
| **dlCard (下载完整应用)** | 显示最新 zip 版本信息 | `is-empty` 状态 → 无版本信息；`is-ready` 状态 → 显示版本号和文件大小，可点击下载 | `test_smoke.py:test_download_latest_api` | P7 |
| **下载链接** | `is-ready` 时点击 | 下载 `GET /download/latest.zip`，浏览器触发文件保存 | `test_smoke.py:test_download_zip` | — |

### 3.5 侧栏底部 — Release 版（更新按钮 + 手动检查）

> **详细更新流程见 [`update-process.md`](update-process.md)**

| 按钮 | 功能 | 预期结果 | 逻辑测试 | 用户测试 |
|------|------|---------|:------:|:------:|
| **upgradeBtn (5 态)** | 更新状态机按钮 | 见下表 5 态详情 | `test_update_check.py` | R10-R15 |
| **btnCheckUpdate (手动检查版本)** | 手动触发更新检查 | 强制请求 `GET /api/update/check?force=1`，显示 toast 结果 | `test_update_check.py` | R4 |

#### upgradeBtn 5 态状态机

| 状态 | CSS class | 按钮文案 | 是否可点 | 触发条件 |
|------|-----------|---------|:------:|---------|
| **检查中** | `is-checking` | "↻ 检查更新中…" | 否(disabled) | 页面加载后初始状态 / 手动触发检查时 |
| **已是最新** | `is-up-to-date` | "✓ 已是最新版本 (vX.Y.Z)" | 否(disabled) | 检查完成 → `comparison ∈ {same, newer}` |
| **有新版本** | `is-available` | "↑ 立即升级 → vX.Y.Z" | **是** | 检查完成 → `has_update == true` + `download_url` 存在 |
| **错误** | `is-error` | "! 无法检查更新，点击重试" | **是** | 检查完成 → `status ∈ {network_error, config_error}` |
| **升级中** | `is-busy` | "… 升级中…" | 否(disabled) | 点击升级按钮后 → POST /api/update/upgrade 执行中 |

### 3.6 Release 版 — 更新横幅

| 行为 | 预期结果 | 逻辑测试 | 用户测试 |
|------|---------|:------:|:------:|
| 有新版本时显示 | 顶部橙色横幅：版本号 + "下载"链接 + "一键升级"按钮 + × 关闭 | `test_update_ui_playwright.py` | R5-R9 |
| 无新版本时不显示 | 横幅保持 `display:none` | — | R6 |
| 点击 × 关闭 | 横幅消失（remove visible class） | — | R7 |
| 点击"一键升级" | 触发 `performUpgrade()` → POST /api/update/upgrade | — | R8 |
| 点击"下载"链接 | 跳转 download_url | — | R9 |

### 3.7 子应用代理

| 行为 | 预期结果 | 逻辑测试 | 用户测试 |
|------|---------|:------:|:------:|
| GET /app/{id}/ | 代理到对应子应用首页，返回 200 | `test_smoke.py:test_proxy_*` | P1 |
| GET /app/{id}/{subpath} | 代理子路径 | `test_smoke.py` | — |

---

## 4. 配置生成 — 按钮功能 & 测试绑定

### 4.1 导航 & 场景选择

| 按钮 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN** (4 个工具标签) | 点击切换工具面板 | 对应面板显示，其他面板隐藏，active 样式切换 | A1 |
| **感谢** | 点击显示感谢页 | 显示贡献者列表 | A2 |
| **我来定模板** | 点击进入模板编辑器 | Cascade menu 渲染，一级菜单 4 项全部显示 | A3 |

### 4.2 版本 & 变体切换

| 按钮 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **4.0 / 5.0** (版本切换) | 切换 ER 版本 | 参数面板根据版本变化；(5.0) 隧道类型按钮出现 | A4 |
| **HK 香港出口 / 非香港出口 / ER 飞连 / ER 新增出口 / ER 域名分流** (变体切换) | 切换场景变体 | 备注说明更新、填写示例更新、参数面板更新 | A5 |
| **OpenVPN / IPSec** (5.0 US 隧道类型) | 切换隧道类型 | 仅在 ER 5.0 非香港出口显示；选中 IPSec → 生成 IPSec 配置 | A28-A32 |

### 4.3 参数设置 — 通用

| 控件 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **数据头 textarea** | 粘贴业务数据头 | 接受粘贴输入 | A6 |
| **Hostname 自动提取** | 从数据头提取 Hostname | 自动填充到 Hostname 输入框 | A6, T3 |
| **清除数据头** | 点击清空数据头 | textarea 清空 | A7 |
| **WAN DHCP 勾选** | 勾选启用 DHCP | WAN IP/网关输入框可能隐藏/禁用 | A10 |
| **LAN DHCP 勾选** | 勾选/取消 DHCP | 相应输入框状态变化 | A11 |
| **生成回程路由 勾选** | 勾选/取消 | 状态切换 | A12 |
| **旁挂模式 勾选** | 勾选 | LAN 接口相关参数隐藏 | A13 |

### 4.4 生成 & 输出

| 按钮 | 功能 | 预期结果 | API | 测试 |
|------|------|---------|-----|:--:|
| **生成配置** (Primary CTA) | 填写数据头 + 参数 → 点击生成 | 输出区显示非空配置文本，含 host-name / set protocols 等关键命令 | POST /api/generate/{tool} | A14, T1, T2 |
| **复制输出** | 点击复制输出内容 | 配置复制到剪贴板，Toast "已复制" | — | A15 |
| **导出脚本** | 点击导出 | 触发 .txt 文件下载 | — | A16 |
| **Ctrl+Enter** | 全局快捷键 | 同「生成配置」 | POST /api/generate/{tool} | A17 |

### 4.5 模板编辑器

| 按钮 | 功能 | 预期结果 | API | 测试 |
|------|------|---------|-----|:--:|
| **场景树 Cascade Menu** | 展开选择模板场景 | 所有层级展开无遮挡，叶子节点文字完整可见 | — | A19 |
| **加载模板** | 点击场景叶子 | 4 个 pane 加载对应内容（数据头、映射、模板、预览） | POST /api/template/load | A20 |
| **编辑模板** | 在 pane 3 修改内容 | 正常编辑 | — | A21 |
| **保存模板** | 修改后点击保存 | 成功 toast | POST /api/template/save | A22 |
| **预览模板** | 点击预览 | 预览区显示生成的配置 | POST /api/template/preview | A23 |
| **恢复最初模板** | 点击重置 | 模板恢复出厂内容 | POST /api/template/reset | A24 |
| **保存初始化** | 点击保存初始化默认值 | 成功保存 | POST /api/init-defaults/save | — |
| **恢复出厂** | 点击恢复出厂默认值 | 初始化默认值重置 | POST /api/init-defaults/reset | — |
| **跨场景隔离** | 场景 A 修改后切场景 B | 场景 B 不受场景 A 修改影响 | — | A25 |
| **模板热更新** | 保存模板 → 主页生成 | 主页生成配置反映新模板 | — | A26 |

### 4.6 API 端点（全部）

| 端点 | 方法 | 用途 | 测试 |
|------|------|------|:--:|
| GET /api/tools | GET | 返回 4 个工具列表 | T1 |
| GET /api/scenarios | GET | 返回场景树 | T1 |
| GET /api/examples/<tool>/<variant> | GET | 返回示例数据 | T1 |
| GET /api/notes/<tool>?variant= | GET | 返回备注说明 | T1 |
| GET /api/sponsor-board | GET | 返回感谢名单 | T1 |
| POST /api/generate/epoch_fastip | POST | 生成 ER 4.0 配置 | T1, T2 |
| POST /api/generate/epoch_fastip5 | POST | 生成 ER 5.0 配置 | T1, T2 |
| POST /api/generate/usg_fastip | POST | 生成 USG 配置 | T1, T2 |
| POST /api/generate/epoch_mpls | POST | 生成 MPLS 配置 | T1, T2 |
| POST /api/generate/ar_sdwan | POST | 生成 AR SD-WAN 配置 | T1, T2 |
| POST /api/template/load | POST | 加载模板 | T4 |
| POST /api/template/save | POST | 保存模板 | T4 |
| POST /api/template/reset | POST | 重置模板 | T4 |
| POST /api/template/preview | POST | 预览模板 | T4 |
| GET /api/init-defaults/<key> | GET | 获取初始化默认值 | — |
| POST /api/init-defaults/save | POST | 保存初始化默认值 | — |
| POST /api/init-defaults/reset | POST | 重置初始化默认值 | — |

---

## 5. 测试报告 — 按钮功能 & 测试绑定

### 5.1 页面 & 表单

| 控件 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **ER FASTIP / USG FASTIP** (产品选择 Radio) | 切换产品类型 | USG → ce_ping_interval_i 禁用、ce_ping_interval_m 启用 | T1 |
| **客户名称** | 输入客户名称 | 接受文本输入 | T2 |
| **CID** | 输入线路 ID (必填) | 接受文本输入，缺失时点击开始应报错 | T2, T6 |
| **带宽** | 输入带宽 | 接受文本输入 | T2 |
| **测试工程师** | 输入工程师名 | 接受文本输入 | T2 |
| **测试日期** | 输入日期 | 接受文本，预填当天日期 | T2 |
| **CE SSH IP** | 输入 CE IP (必填) | 接受文本输入 | T2 |
| **CE端口** | 输入端口 | 默认 "2707" | T2 |
| **CE用户名** | 输入用户名 | 默认 "bothwin" | T2 |
| **CE密码** | 输入密码 | 密码类型输入框 | T2 |
| **主线对端IP** (必填) | 输入主线 IP | 接受文本输入 | T2 |
| **备线IP** (必填) | 输入备线 IP | 接受文本输入 | T2 |
| **本地站点** | 输入本地站点 URL | 默认 "www.baidu.com" | T2 |
| **加速站点** | 输入加速站点 URL | 默认 "www.google.com" | T2 |

### 5.2 CE 密码预设

| 按钮 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **bothwin/Tfe** | 选择预设 | 自动填入 user="bothwin", password="Tfe28@w%" | T2 |
| **admin/Tfe** | 选择预设 | 自动填入 user="admin", password="Tfe28@w%" | T2 |
| **bothwin/.x12** | 选择预设 | 自动填入 user="bothwin", password=".x12Tfe192Ti.2024" | T2 |
| **aaa（自定义）** | 选择自定义 | 显示 user/password 自定义输入框 | T2 |
| **保存密码** | 保存自定义密码 | 填入 CE 字段 | T2 |

### 5.3 操作按钮

| 按钮 | 功能 | 预期结果 | API | 测试 |
|------|------|---------|-----|:--:|
| **开始生成报告** (Primary) | 点击开始测试 | 必填字段验证通过 → POST /api/run → 返回 task_id → SSE 日志流开始 → 按钮显示 "运行中..." | POST /api/run | T3, T6 |
| **中断** (Secondary) | 点击停止测试 | POST /api/stop → 进程终止 | POST /api/stop | T4 |
| **清空日志** | 点击清空日志区 | `<pre>` 日志区清空 | — | — |
| **下载报告** (Toast) | 完成后点击下载 | GET /api/download/<filename> → 下载 .docx 文件 | GET /api/download/<filename> | T5 |

### 5.4 API 端点

| 端点 | 方法 | 用途 | 测试 |
|------|------|------|:--:|
| POST /api/run | POST | 启动报告生成 | T1-T3 |
| POST /api/stop | POST | 停止任务 | T4, T7 |
| GET /api/logs/<task_id> | GET (SSE) | 实时日志流 | T4 |
| GET /api/download/<path:filename> | GET | 下载报告文件 | T8 |

---

## 6. 域名抓取 — 按钮功能 & 测试绑定

### 6.1 输入 & 抓取

| 控件 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **URL 输入框** | 输入目标网址 | 接受文本，回车触发抓取 | D2 |
| **抓取 button** (Primary) | 点击开始抓取 | POST /api/capture → 显示 loading spinner → 结果区显示域名列表 | D3, D1 |
| **Timeout 输入** | 设置超时 | 范围 5-120s，默认 30s | D6 |
| **Wait 输入** | 设置页面等待 | 范围 0-30s，默认 3s | — |
| **包含 IP checkbox** | 是否包含 IP | 勾选 → 结果含 IP 条目 | D4, D4 |
| **解析 CNAME checkbox** | 是否解析 DNS CNAME | 默认勾选 → 结果含 CNAME 链路 | D3, D3 |

### 6.2 结果操作

| 按钮 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **全部展开** | 点击展开所有 CNAME 子节点 | 所有域名 CNAME 链展开，按钮变为 "全部折叠" | — |
| **复制** | 点击复制可见域名 | 剪贴板获取域名列表 | — |
| **导出** | 点击导出文件 | 下载 `domains_export.txt`（含折叠项） | — |
| **域名行 click** | 点击展开/折叠 CNAME 链 | 箭头旋转，子节点展开/折叠 | — |

### 6.3 API 端点

| 端点 | 方法 | 用途 | 测试 |
|------|------|------|:--:|
| POST /api/capture | POST | 抓取域名 | D1-D8 |

---

## 7. 配置梳理 — 按钮功能 & 测试绑定

### 7.1 输入

| 控件 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **ER / USG Tab** | 切换解析模式 | 默认 ER，点击 USG 切换 | C2, C3 |
| **配置脚本 textarea** | 粘贴配置文本 | 接受 VyOS/USG 配置 | C4 |
| **文件导入** | 选择文件导入 | 接受 .txt/.cfg/.conf/.log，内容填入 textarea | CA10 |
| **假IP→真IP 映射 textarea** | 粘贴 IP 映射 | 支持 `-`, `=`, `:`, `->` 分隔符 + 分号/换行 | CA7 |

### 7.2 工具栏

| 按钮 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **解析并梳理** (Primary) | 点击解析配置 | 客户端解析 → NAT 表、拓扑 SVG、账本、IP 摘要全部更新 | C5, CA2-CA6 |
| **导出CSV** | 点击导出 NAT 表 | 下载 CSV 文件 | C9 |
| **清空** | 点击清空所有输入 | textarea 清空 | — |
| **接受备注启发式判断** (checkbox) | 启用备注推断 | 接口描述中的主/备标记被识别 | — |

### 7.3 结果展示

| 控件 | 功能 | 预期结果 | 测试 |
|------|------|---------|:--:|
| **NAT表 Tab** | 默认显示 NAT 规则 | Rule、源IP/网段、出口接口、出口备注、假IP、真IP | C6 |
| **ER Topology Tab** | 显示拓扑 SVG | 主线/备线/未知线路分车道，隧道自动配色 | C6, C7, C8, C9 |
| **解析备注 Tab** | 显示未消费行 | 等宽字体 | — |
| **IP摘要 Tab** | 显示 IP 汇总 | 等宽字体 | — |
| **+ / - / 重置** (缩放) | 控制拓扑缩放 | SVG 缩放变化 | C11 |
| **拖拽画布** | 拖拽平移拓扑 | 拖拽响应 | — |

### 7.4 特殊场景

| 行为 | 预期结果 | 测试 |
|------|---------|:--:|
| 空配置 | 解析返回空结果，不崩溃 | CA12 |
| 畸形配置 | 优雅降级，不崩溃 | CA13 |

---

## 8. 更新模块 — 功能 & 测试绑定

> **详细更新流程见 [`update-process.md`](update-process.md)**

### 8.1 更新检查

| 功能 | API | 预期结果 | 测试 |
|------|-----|---------|:--:|
| 检查更新 | GET /api/update/check | 返回 `{status, local_version, remote_version, has_update, ...}` | R1 |
| 强制刷新 | GET /api/update/check?force=1 | 跳过缓存，重新请求所有源 | R4 |
| Mirror 可达 | — | status="ok" | R2 |
| Mirror 不可达 | — | status="network_error"，不崩溃 | R2 |
| 本地版本 | — | 从 RELEASE_INFO.json 读取 | R3 |
| 缓存机制 | — | 默认 3600s TTL，force=1 跳过 | — |

### 8.2 升级执行

| 功能 | API | 预期结果 | 测试 |
|------|-----|---------|:--:|
| 执行升级 | POST /api/update/upgrade {download_url} | 返回 `{ok:true, new_version}` | R16 |
| 下载 zip | — | 带进度，120s 超时 | R17 |
| 验证 zip | — | 含 RELEASE_INFO.json 才合法 | R17 |
| 生成 update.bat | — | 6 步升级脚本（等待退出→杀端口→备份→解压→恢复→重启） | R17 |
| 备份用户数据 | — | 备份 editor_workspace, user_init_placeholders, .update_cache | R17 |
| 下载失败 | — | 返回 {ok:false, error, stage} | R13 |

### 8.3 重启

| 功能 | API | 预期结果 | 测试 |
|------|-----|---------|:--:|
| 关闭 Portal | POST /api/shutdown | 返回 {ok:true}，进程退出 | R19 |
| 重新启动 | start_all.bat | 新版本生效 | R20 |

---

## 9. 构建 & 发版

### 9.1 构建流程

```
git checkout release
py tools/release.py <version>      # 一键发版（构建+推送+验证）
py tools/release.py <version> --no-push  # 仅本地测试
```

### 9.2 构建后验证

| 验证项 | 命令 | 预期 |
|--------|------|------|
| pytest 全量 | `py -m pytest application/test/ -v` | 100% PASS |
| 客户模拟测试 | `py application/test/portal/test_customer_full.py` | 100% PASS |
| zip 校验 | `py tools/_verify_zip.py dist/<file>.zip <version>` | 25 checks PASS |
| 更新 UI 测试 | `py -m pytest application/test/portal/test_update_ui_playwright.py -v` | 100% PASS |

### 9.3 Mirror 服务

```powershell
# 启动 mirror（Demo 自动，Release 手动）
py tools/serve_mirror.py --port 8000 --dist dist

# 验证 mirror 在线
curl http://127.0.0.1:8000/api/update/manifest
```

---

## 10. 测试工具索引

### 10.1 测试分类

| 类别 | 工具 | 覆盖范围 |
|------|------|---------|
| **代码逻辑** | pytest | API 端点、业务逻辑、生成正确性、模板系统、参数处理、错误处理 |
| **用户行为** | Playwright (browser) | 按钮点击、页面渲染、表单交互、视觉验证、控制台错误 |
| **构建验证** | pytest + 脚本 | zip 内容校验、bat 文件验证、端口替换验证 |
| **更新链路** | pytest + Playwright | 版本检查、升级流程、mirror 可达性、横幅显示 |
| **启动验证** | 脚本 | bat 启动、进程管理、端口占用、健康检查 |

### 10.2 测试文件全量清单 & 功能绑定

#### 更新模块测试（8 个文件）

| # | 测试文件 | 类型 | 绑定的功能 |
|---|---------|------|-----------|
| 1 | `application/test/portal/test_update_check.py` | 代码逻辑 | 版本比较、配置加载、网络失败、缓存、多源 fallback |
| 2 | `application/test/portal/test_update_ui_playwright.py` | Playwright | 横幅出现、5态按钮、手动检查、升级按钮状态转换 |
| 3 | `application/test/portal/test_customer_full.py` | 客户模拟 | 解压→启动→检查更新→横幅→升级→控制台错误 |
| 4 | `application/test/portal/test_update_e2e.py` | E2E | 构建→mirror→demo→release→升级→数据保留 |
| 5 | `application/test/portal/test_update_flow.py` | 代码逻辑 | 端口验证、更新检查 API、mirror URL 配置 |
| 6 | `application/test/portal/test_upgrade_playwright.py` | Playwright | 升级按钮交互 |
| 7 | `application/test/portal/test_release.py` | 代码逻辑 | Release 版功能开关、版本号、更新检查响应 |
| 8 | `application/test/portal/test_smoke.py` | 代码逻辑 | /api/update/check 端点、/api/update/upgrade 端点 |

#### Portal 测试（3 个文件）

| # | 测试文件 | 绑定的功能 |
|---|---------|-----------|
| 1 | `application/test/portal/test_smoke.py` | Portal 首页、状态 API、下载 API、代理、更新端点 |
| 2 | `application/test/portal/test_release.py` | Release 版本验证 |
| 3 | `application/test/portal/check_zip.py` | zip 内容校验 |

#### 配置生成测试（18 个文件）

| # | 测试文件 | 绑定的功能 |
|---|---------|-----------|
| 1 | `test_apis.py` | 全部 18 API 端点 |
| 2 | `test_business.py` | Hostname/DHCP/回程路由/旁挂/NAT/BGP |
| 3 | `test_generation.py` | 28+ 场景-版本组合生成 |
| 4 | `test_templates.py` | 模板 CRUD/预览/隔离/热更新 |
| 5 | `test_params.py` | 空输入/缺失字段/特殊字符/超长/Unicode |
| 6 | `test_e2e.py` | Flask test client 完整流程 |
| 7 | `test_e2e_playwright.py` | 浏览器全功能 E2E |
| 8 | `test_er5_ipsec.py` | IPSec 模板完整性 |
| 9 | `test_er5_ipsec_api.py` | IPSec API 正确响应 |
| 10 | `test_er5_ipsec_content.py` | IPSec 生成内容逐项检查 |
| 11 | `test_template_editor_e2e.py` | 场景树/IPSec/OpenVPN/保存/热更新 |
| 12 | `test_hostname_all.py` | Hostname 全场景提取 |
| 13 | `test_mpls_bypass.py` | MPLS bypass 路由 |
| 14 | `test_usg_return_routes.py` | USG 回程路由 |
| 15-18 | `test_er5/test_*.py` + tools | 专项场景 |

#### 测试报告/域名抓取/配置梳理（6 个文件）

| # | 测试文件 | 绑定的功能 |
|---|---------|-----------|
| 1 | `test_report/test_smoke.py` | 页面加载 |
| 2 | `test_report/test_api.py` | /api/run, /api/stop, /api/logs, /api/download |
| 3 | `domain_capture/test_smoke.py` | 页面加载 |
| 4 | `domain_capture/test_api.py` | /api/capture 抓取/CNAME/IP/超时 |
| 5 | `config_analyzer/test_smoke.py` | 页面加载 + DOM 元素 |
| 6 | `config_analyzer/test_e2e_playwright.py` | 解析/拓扑/CSV/缩放 |

#### 构建验证（2 个文件）

| # | 测试文件 | 绑定的功能 |
|---|---------|-----------|
| 1 | `tools/test_build_release.py` | 构建逻辑、排除规则 |
| 2 | `tools/_verify_zip.py` | zip 25 项校验 |

**总计: 38 个测试文件，覆盖 5 个应用 + 更新模块 + 构建流程。**

### 10.3 测试通过标准

- **代码逻辑测试:** 所有用例 100% PASS（`pytest ... -v` 无 FAILED/ERROR）
- **Playwright 测试:** 所有检查项 PASS，控制台零 JS 错误
- **构建验证:** 25 项 check 全部 PASS
- **客户模拟:** 解压 → 启动 → 检测更新 → 验证 UI 完整链路 PASS
- **发版前:** 以上 4 项全部通过 + 至少 1 次完整端到端更新测试
