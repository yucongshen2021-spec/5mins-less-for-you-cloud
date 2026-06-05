# 测试工具统一管理 — 帮你节省5分钟

> **目标：** 统一管理项目所有测试工具，定义测试分类、命名规范、执行顺序、通过标准。以后所有测试按此文档执行。
>
> **原则：** 逻辑测试验证后端，Playwright 验证用户体验。两者缺一不可。

---

## 目录

1. [测试架构总览](#1-测试架构总览)
2. [测试工具清单](#2-测试工具清单)
3. [测试分类 & 命名规范](#3-测试分类--命名规范)
4. [测试执行矩阵](#4-测试执行矩阵)
5. [测试命令速查](#5-测试命令速查)
6. [测试执行顺序](#6-测试执行顺序)
7. [通过标准](#7-通过标准)
8. [测试数据管理](#8-测试数据管理)
9. [测试环境](#9-测试环境)

---

## 1. 测试架构总览

```
application/test/
├── _smoke_helpers.py                    # Portal + 子应用 smoke test 共享工具
│
├── all_in_one/                          # 配置生成 — 18 个测试文件
│   ├── _bootstrap.py                    # 环境初始化
│   ├── common.py                        # 共享夹具
│   ├── conftest.py                      # pytest fixtures
│   ├── test_apis.py                     # API 端点测试
│   ├── test_business.py                 # 业务逻辑测试
│   ├── test_generation.py               # 生成结果正确性测试
│   ├── test_templates.py                # 模板系统测试
│   ├── test_params.py                   # 参数处理测试
│   ├── test_e2e.py                      # Flask test client E2E
│   ├── test_e2e_playwright.py           # Playwright 全功能 E2E
│   ├── test_template_editor_e2e.py      # 模板编辑器 E2E
│   ├── test_hostname_all.py             # Hostname 全场景测试
│   ├── test_mpls_bypass.py              # MPLS bypass 路由测试
│   ├── test_usg_return_routes.py        # USG 回程路由测试
│   ├── test_er5_ipsec.py                # ER 5.0 IPSec 测试
│   ├── test_er5_ipsec_api.py            # ER 5.0 IPSec API 测试
│   ├── test_er5_ipsec_content.py        # ER 5.0 IPSec 内容测试
│   ├── test_er5/test_hk_generation.py   # HK IPSec 生成验证
│   ├── test_er5/test_flink_generation.py # Flink IPSec 生成验证
│   ├── comprehensive.py                 # 全量回归脚本
│   ├── compare.py                       # 配置差异对比工具
│   └── audit_templates.py               # 模板审计工具
│
├── portal/                              # Portal — 8 个测试文件
│   ├── test_smoke.py                    # Portal smoke test
│   ├── test_release.py                  # Release 功能测试
│   ├── test_update_check.py             # (在 portal/ 根目录) 更新检查逻辑
│   ├── test_update_e2e.py               # 更新端到端测试
│   ├── test_update_flow.py              # 更新流程测试
│   ├── test_update_ui_playwright.py     # 更新 UI Playwright 测试
│   ├── test_upgrade_playwright.py       # 升级 Playwright 测试
│   ├── test_customer_full.py            # 完整客户模拟测试
│   └── check_zip.py                     # zip 内容校验
│
├── test_report/                         # 测试报告 — 2 个测试文件
│   ├── test_smoke.py                    # Smoke test
│   └── test_api.py                      # API 测试
│
├── domain_capture/                      # 域名抓取 — 2 个测试文件
│   ├── test_smoke.py                    # Smoke test
│   └── test_api.py                      # API 测试
│
└── config_analyzer/                     # 配置梳理 — 2 个测试文件
    ├── test_smoke.py                    # Smoke test
    └── test_e2e_playwright.py           # Playwright E2E 测试

tools/
├── test_build_release.py                # 构建脚本逻辑测试
├── _verify_zip.py                       # zip 包 25 项校验工具
└── simulate_customer.py                 # 客户环境模拟器
```

---

## 2. 测试工具清单

### 2.1 一级测试工具（直接运行）

| # | 工具 | 类型 | 路径/命令 | 用途 |
|---|------|------|----------|------|
| 1 | **pytest 全量** | 代码逻辑 | `py -m pytest application/test/ -v` | 所有代码逻辑测试 |
| 2 | **Playwright Portal E2E** | 用户行为 | `mcp__plugin_playwright_playwright` | Portal 真实浏览器测试 |
| 3 | **Playwright all_in_one E2E** | 用户行为 | `application/test/all_in_one/test_e2e_playwright.py` | 配置生成浏览器测试 |
| 4 | **Playwright config_analyzer E2E** | 用户行为 | `application/test/config_analyzer/test_e2e_playwright.py` | 配置梳理浏览器测试 |
| 5 | **更新 UI Playwright** | 用户行为 | `py -m pytest application/test/portal/test_update_ui_playwright.py -v` | 更新按钮/横幅浏览器测试 |
| 6 | **客户模拟测试** | 端到端 | `py application/test/portal/test_customer_full.py` | 解压→启动→检查更新→验证 UI |
| 7 | **zip 校验** | 构建验证 | `py tools/_verify_zip.py dist/<file>.zip <version>` | 25 项构建产物校验 |
| 8 | **build_release 逻辑** | 构建验证 | `py -m pytest tools/test_build_release.py -v` | 构建脚本逻辑测试 |

### 2.2 二级测试工具（辅助/手动）

| # | 工具 | 路径 | 用途 |
|---|------|------|------|
| 9 | comprehensive.py | `application/test/all_in_one/comprehensive.py` | 全量回归脚本 |
| 10 | compare.py | `application/test/all_in_one/compare.py` | 配置差异对比 |
| 11 | audit_templates.py | `application/test/all_in_one/audit_templates.py` | 模板审计 |
| 12 | check_zip.py | `application/test/portal/check_zip.py` | zip 内容校验 |
| 13 | simulate_customer.py | `tools/simulate_customer.py` | 客户环境模拟 |

### 2.3 测试辅助基础设施

| 组件 | 路径 | 用途 |
|------|------|------|
| _smoke_helpers.py | `application/test/_smoke_helpers.py` | Portal + 子应用共享 smoke test 工具 |
| common.py | `application/test/all_in_one/common.py` | 共享夹具 |
| conftest.py | `application/test/all_in_one/conftest.py` | pytest fixtures |
| _bootstrap.py | `application/test/all_in_one/_bootstrap.py` | 环境初始化 |

---

## 3. 测试分类 & 命名规范

### 3.1 按测试类型分类

| 类别 | 标识 | 说明 | 文件命名 |
|------|:----:|------|---------|
| **Smoke Test** | S | HTTP 200 + 基本 HTML 元素存在 | `test_smoke.py` |
| **API Test** | A | 端点响应码 + 返回格式 + 数据正确性 | `test_api.py`, `test_apis.py` |
| **Business Logic** | B | 业务规则正确性（生成内容、参数处理等） | `test_business.py` |
| **Generation Test** | G | 生成结果逐项校验（关键配置行） | `test_generation.py` |
| **Template Test** | T | 模板 CRUD + 预览 + 隔离 + 热更新 | `test_templates.py` |
| **Parameter Test** | P | 边界情况、非法输入、特殊字符 | `test_params.py` |
| **E2E (Flask client)** | E | Flask test client 完整流程 | `test_e2e.py` |
| **E2E (Playwright)** | PW | 真实浏览器用户操作 | `test_e2e_playwright.py` 或 `*playwright*.py` |
| **Update/Upgrade** | U | 更新检查、升级流程 | `test_update_*.py`, `test_upgrade_*.py` |
| **Build Verify** | BV | 构建产物校验 | `test_build_release.py`, `_verify_zip.py` |
| **Customer Sim** | CS | 客户环境端到端模拟 | `test_customer_full.py` |
| **Specialized** | SP | 专项功能（IPSec、Hostname、MPLS 等） | `test_<feature>.py` |

### 3.2 命名规范

```
test_<type>.py              基础类型测试
test_<feature>.py           专项功能测试
test_<feature>_<sub>.py     专项功能子场景（如 test_er5_ipsec_api.py）
test_e2e.py                 Flask client E2E
test_e2e_playwright.py      Playwright E2E
test_*_playwright.py        Playwright 专项测试
```

---

## 4. 测试执行矩阵

### 4.1 应用 × 测试类型 覆盖矩阵

| 应用 | Smoke | API | Business | Generation | Params | E2E (Flask) | E2E (PW) | 最低通过率 |
|------|:-----:|:---:|:--------:|:----------:|:------:|:-----------:|:--------:|:--------:|
| 配置生成 (all_in_one) | — | ✓ (T1) | ✓ (T3) | ✓ (T2) | ✓ (T5) | ✓ | ✓ (A1-A58) | **100%** |
| 测试报告 (test_report) | ✓ | ✓ (T1-T8) | — | — | — | — | ✓ (T1-T8) | **100%** |
| 域名抓取 (domain_capture) | ✓ | ✓ (D1-D8) | — | — | — | — | ✓ (D1-D6) | **100%** |
| 配置梳理 (config_analyzer) | ✓ | — | — | — | — | — | ✓ (C1-C10) | **100%** |
| Portal 总控 | ✓ | ✓ | — | — | — | — | ✓ (P1-P13) | **100%** |
| 更新模块 | — | ✓ | — | — | — | — | ✓ (R1-R20) | **100%** |

### 4.2 Portal 测试矩阵（Demo vs Release）

| 测试项 | Demo (:5000) | Release (:7000) |
|--------|:-----------:|:---------------:|
| test_smoke.py | ✓ | ✓ |
| test_release.py | — | ✓ |
| test_update_check.py | — | ✓ |
| test_update_e2e.py | — | ✓ |
| test_update_flow.py | — | ✓ |
| test_update_ui_playwright.py | — | ✓ |
| test_upgrade_playwright.py | — | ✓ |
| test_customer_full.py | — | ✓ |
| check_zip.py | — | ✓ |
| P1-P12 (Playwright Portal) | ✓ (P1-P12) | ✓ (P1-P12) |
| R1-R20 (Playwright Release) | — | ✓ (R1-R20) |

---

## 5. 测试命令速查

### 5.1 日常开发（修改代码后必要）

```powershell
# 1. 全量 pytest（代码逻辑层 — 必跑）
py -m pytest application/test/ -v

# 2. 仅跑 3 个子应用（快速验证）
py -m pytest application/test/test_report/ application/test/domain_capture/ application/test/config_analyzer/ application/test/portal/ -v
```

### 5.2 更新功能测试

```powershell
# Portal 更新 UI Playwright 测试（真实浏览器点击按钮）
py -m pytest application/test/portal/test_update_ui_playwright.py -v

# 完整客户模拟测试（解压 zip → 启动 → 检测更新 → 验证 UI）
# 必须通过才能发版
py application/test/portal/test_customer_full.py
```

### 5.3 构建验证

```powershell
# 构建后 zip 校验（25 项检查）
py tools/_verify_zip.py dist/帮你节省5分钟-<version>.zip <version>

# 构建脚本逻辑测试
py -m pytest tools/test_build_release.py -v
```

### 5.4 专项测试

```powershell
# ER 5.0 IPSec 测试
py -m pytest application/test/all_in_one/test_er5_ipsec*.py -v

# 模板编辑器
py -m pytest application/test/all_in_one/test_template_editor_e2e.py -v

# Hostname 全场景
py -m pytest application/test/all_in_one/test_hostname_all.py -v
```

### 5.5 Playwright E2E（不走 pytest）

```powershell
# 配置生成浏览器 E2E
py application/test/all_in_one/test_e2e_playwright.py

# 配置梳理浏览器 E2E
py application/test/config_analyzer/test_e2e_playwright.py
```

---

## 6. 测试执行顺序

### 6.1 日常开发流程

```
修改代码
  │
  ├─→ 1. pytest 全量（代码逻辑层）   ~90s    ← 必须 100% PASS
  │
  ├─→ 2. Portal 导航 Playwright       ~60s    ← 4 个 iframe 正确加载
  │
  ├─→ 3. 配置生成 Playwright          ~180s   ← 至少 1 个场景完整走通
  │
  └─→ 4. 控制台零错误                 ~10s    ← 除 favicon 404
```

### 6.2 发版前全量验证流程

```
发版前检查
  │
  ├─→ 1. git checkout release         确认在 release 分支
  ├─→ 2. pytest 全量                  所有 144+ cases 100% PASS
  ├─→ 3. bat 源码验证                 chcp 65001 / PYTHONNOUSERSITE 条件 / 端口列表
  ├─→ 4. Playwright Demo (500x)       所有 P/A/T/D/C/X 检查项
  ├─→ 5. Playwright Release (700x)    所有 P/A/T/D/C/R/X 检查项
  ├─→ 6. UI 合规检查                  字体、颜色、间距符合 DESIGN.md
  ├─→ 7. 控制台零错误                 全部页面无 JS 错误
  ├─→ 8. 构建                         py tools/release.py <version>
  ├─→ 9. 构建后 bat 校验              chcp 65001 未破坏 / 端口 700x / 中文 echo 未乱码
  ├─→ 10. zip 解压端到端              启动 → 4 个子应用可访问
  ├─→ 11. 更新链路测试                启动 mirror → check → 横幅 → 升级
  └─→ 12. commit + push
```

---

## 7. 通过标准

### 7.1 代码逻辑测试（pytest）

- **必须 100% PASS** — 任何 FAILED/ERROR 都不允许
- 允许 skip（标记为已知未实现）
- 必须覆盖：正常路径 + 边界情况 + 错误处理

### 7.2 Playwright 用户行为测试

- **所有检查项 PASS**
- **控制台零 JS 错误**（favicon 404 除外）
- **无文字遮盖或布局溢出**
- **所有按钮可点击且有响应**
- **颜色/间距/字体符合 DESIGN.md**

### 7.3 构建验证

- zip 25 项 check 全部 PASS
- bat 文件验证：chcp 65001 存在、chcp 67001 不存在、端口 700x、纯 ASCII
- zip 内含 RELEASE_INFO.json
- zip 内无 runtime/ 重复打包

### 7.4 客户模拟测试

- 从 zip 解压到临时目录
- 双击 start_all.bat 启动
- portal 首页可访问（端口 7000）
- 4 个子应用全部 online
- 更新检查返回 status: ok
- 控制台无 Python traceback

---

## 8. 测试数据管理

### 8.1 配置生成测试数据

- 使用 `/api/examples/<tool>/<variant>` 返回的官方示例数据
- 严禁猜测参数值
- 新增场景必须同步添加示例数据

### 8.2 配置梳理测试数据

- 标准 VyOS 配置片段（见 `plan/full-testing-standard.md` §5.2）
- 覆盖 ER 和 USG 两种场景

### 8.3 域名抓取测试 URL

- `https://www.baidu.com`
- `https://www.example.com`
- 注意：外部 URL 可能因网络变化而失败，需有 fallback

### 8.4 更新测试数据

- dist/ 需要两个 zip（旧版 + 新版）同时存在
- 旧版 = 模拟客户环境
- 新版 = 更新目标

---

## 9. 测试环境

### 9.1 端口分配

| 组件 | Demo | Release |
|------|------|---------|
| Portal | 5000 | 7000 |
| 域名抓取 | 5001 | 7001 |
| 测试报告 | 5002 | 7002 |
| 配置生成 | 5003 | 7003 |
| 配置梳理 | 5004 | 7004 |
| Mirror | 8000 | 8000 |

### 9.2 测试前清理

```powershell
# 1. 检查无残留进程
foreach ($p in @(5000..5004 + 7000..7004 + 8000)) {
    netstat -ano | Select-String ":$p " | Select-String "LISTENING"
}
# 如有残留 → taskkill

# 2. 清理 __pycache__
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# 3. 确认分支
git branch

# 4. 删除 .update_cache.json（如需测试更新）
Remove-Item application/portal/.update_cache.json -ErrorAction SilentlyContinue
```

### 9.3 Demo 版启动

```powershell
# 自动启动 mirror on :8000
py application/portal/app.py
# → Portal on :5000 + mirror on :8000
```

### 9.4 Release 版启动

```powershell
$env:RELEASE_MODE = "1"
py application/portal/app.py
# → Portal on :7000（不自动启动 mirror）
# → 需要手动启动 mirror:
#   py tools/serve_mirror.py --port 8000
```
