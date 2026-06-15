# Update E2E Test Consolidation — Design

> 日期: 2026-06-15
> 状态: approved

## 目标

将当前 3 个功能重叠的 E2E 测试文件整合为 2 个，消除重复代码，修复依赖问题。

## 当前状态

| 文件 | 行数 | 问题 |
|------|------|------|
| `test_update_e2e.py` | 142 | 依赖 `requests` 非标准库，功能最弱 |
| `test_upgrade_playwright.py` | 405 | 硬编码版本号，自建 zip 而非用 dist/ |
| `test_upgrade_real_e2e.py` | 441 | 最完整，但独立脚本无 pytest 集成 |

公共逻辑（`port_open`、`kill_ports`、`garbled_files` 等）跨 3 个文件重复 ~150 行。

## 最终产出

### File 1: `test_update_smoke.py` (~120 lines)

轻量冒烟测试 — 纯标准库，< 15s。

**验证链路**（顺序执行）：
1. Mirror manifest 可访问 (`/api/update/manifest`)
2. Download URL 合法（URL decode 后确认不含中文残留）
3. 解压 dist/ 中最旧 zip → 修改 `update_config.json` 指向 localhost mirror
4. `GET /api/update/check?force=1` → `has_update: true`
5. `GET /` → HTML 含 `#upgradeBtn`、`#updateBanner` 等关键 DOM 元素

**依赖**: 纯标准库 (`urllib.request` + `json` + `zipfile` + `subprocess` + `re`)。

### File 2: `test_upgrade_e2e.py` (~470 lines)

完整端到端测试 — 以 `test_upgrade_real_e2e.py` 为主体，吸收另外两个文件的优点（garbled 文件名检查、banner 文案断言），加入 pytest fixtures。

**验证链路**（顺序执行）：
1. 解压最旧 zip → 启动 customer portal (port 700x)
2. Playwright 打开 → 等待 `#updateBanner` 出现 → 验证版本号文案
3. 点击 "一键升级" → 触发升级
4. 轮询端口等 portal 退出 → 等 bat 完成 → 等重启
5. Playwright 重新打开 → 验证新版本号 → 验证无乱码文件名
6. 检查 `#upgradeBtn.is-up-to-date`
7. 检查 mirror 日志无 "fail"、"error"（大小写不敏感）

### 共享模块: `_update_utils.py` (~80 lines)

提取公共函数到 `application/test/portal/_update_utils.py`：

| 函数 | 来源 | 用途 |
|------|------|------|
| `port_open(port, timeout)` | 3 个文件共有 | 轮询端口是否 LISTENING |
| `kill_ports(start, end)` | `test_upgrade_real_e2e.py` | 强杀端口范围 |
| `http_get(url, timeout)` | smoke test | GET 请求（urllib） |
| `find_content_in_html(html, selectors)` | smoke test | 检查 HTML 含指定 CSS selector |
| `check_garbled_filenames(dir)` | `test_upgrade_real_e2e.py` | 检查无乱码文件名 |
| `unzip_and_configure(zip, mirror_url)` | 公用 | 解压 + 注入 mirror 配置 |

### 清理

- **删除**: `test_update_e2e.py`、`test_upgrade_playwright.py`
- **重命名**: `test_upgrade_real_e2e.py` → `test_upgrade_e2e.py`

## 不变更

- `test_upgrade_bat.py` — 保持不动（单元测试，独立职责）
- `test_upgrade_url_encode.py` — 保持不动
- `test_customer_full.py` — 保持不动（业务逻辑测试，非更新链路专属）
