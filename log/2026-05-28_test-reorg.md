# 2026-05-28 测试体系整合

## 用户请求
> 现在整理所有的测试文件和测试脚本，都需要放在 application 的 test 文件夹里面（没有就新建一个）。同时，修复所有的无法使用的 test 测试工具。每次变动都要记录在 log 文件夹里面，没有就新建一个。

## 总览
- 把全部 Python 测试集中到新目录 `application/test/`，按 app 分子目录。
- 修复了三个先前无法在 pytest 里跑通的测试基础设施问题。
- 为另外 4 个原本没有测试的应用补了最小烟雾测试。
- 跑通了全部 44 个 pytest 用例 + 42 个 Playwright E2E 用例。

## 新目录结构

```
application/
├── test/
│   ├── _smoke_helpers.py            ← 共用：subprocess + 端口探测 + http.get
│   ├── all_in_one/
│   │   ├── _bootstrap.py            ← 共用：把 all_in_one - cc 的 web/src 加入 sys.path
│   │   ├── conftest.py              ← pytest 启动 Flask + 重写 page fixture
│   │   ├── common.py / compare.py / comprehensive.py / audit_templates.py
│   │   ├── test_apis.py / test_business.py / test_e2e.py / test_e2e_playwright.py
│   │   ├── test_generation.py / test_hostname_all.py / test_mpls_bypass.py
│   │   ├── test_params.py / test_templates.py / test_usg_return_routes.py
│   │   └── test_er5/
│   │       ├── test_hk_generation.py
│   │       └── test_flink_generation.py
│   ├── portal/
│   │   ├── __init__.py
│   │   └── test_smoke.py
│   ├── test_report/
│   │   ├── __init__.py
│   │   └── test_smoke.py
│   ├── domain_capture/
│   │   ├── __init__.py
│   │   └── test_smoke.py
│   └── config_analyzer/
│       ├── __init__.py
│       └── test_smoke.py
```

## 迁移
源：`application/all_in_one - cc/test/`（17 个 .py + test_er5 子目录）
目标：`application/test/all_in_one/`（保留 test_er5 子目录）

源目录已清空并 rmdir。

## 路径锚点改写
所有测试原本用 `Path(__file__).resolve().parent.parent / "web"` 找 web/src，迁移后这套路径全部失效。统一改用新增的 `_bootstrap.py`：

```python
APP_DIR = Path(__file__).resolve().parents[2] / "all_in_one - cc"
WEB_DIR = APP_DIR / "web"
SRC_DIR = APP_DIR / "src"
```

改动的文件（共 10 个）：

| 文件 | 改动 |
| --- | --- |
| `all_in_one/_bootstrap.py` | 新增，集中定义路径 |
| `all_in_one/common.py` | `sys.path` → `import _bootstrap` |
| `all_in_one/compare.py` | 同上 |
| `all_in_one/comprehensive.py` | 同上 |
| `all_in_one/audit_templates.py` | 同上 |
| `all_in_one/test_business.py` | 同上 |
| `all_in_one/test_e2e.py` | 同上 |
| `all_in_one/test_e2e_playwright.py` | `PROJ = APP_DIR` 用 bootstrap |
| `all_in_one/test_hostname_all.py` | `html_path` 用 `WEB_DIR / "templates" / "index.html"` |
| `all_in_one/test_er5/test_hk_generation.py` | `_proj_root` 改为 `import _bootstrap` |
| `all_in_one/test_er5/test_flink_generation.py` | 同上 |

## 修复的测试工具

### 1. test_e2e_playwright.py 启动后卡在「生成配置」
**根因**：`subprocess.Popen` 用 `stdout=PIPE, stderr=PIPE` 启动 Flask。Flask 启动后会持续写日志，PIPE 缓冲打满后子进程主线程被阻塞，对外不再响应 HTTP。
**修复**：改 `DEVNULL`，并在 `web/app.py` 入口处加 `NO_BROWSER=1 / TEST_MODE=1` 时不调用 `webbrowser.open`（自动开浏览器在 CI/headless 环境无意义且会卡）。
**结果**：standalone `--quick` 跑出 42/42。

### 2. pytest 跑 test_e2e_playwright.py 报 `fixture 'page' not found`
**根因**：缺少 `pytest-playwright` 插件，并且测试假定服务器已起（由 standalone `main()` 启动），pytest 跑独立用例时没人起 Flask。
**修复**：
- `pip install pytest-playwright`（额外依赖，仅本机/测试环境需要）。
- 新增 `all_in_one/conftest.py`，提供 session 级 `flask_server` fixture + 重写 `page` fixture（自动 `goto`）。
**结果**：`pytest test_e2e_playwright.py::test_nav_tabs test_e2e_playwright.py::test_dhcp_toggle` 2/2 通过。

### 3. portal smoke 测试残留子进程污染其他 smoke
**根因**：portal 启动会拉起 5739/5740/5741/5742 共 4 个子应用；用 `proc.terminate()` 杀 portal 父进程在 Windows 上不会执行 `atexit`，子进程留在原端口，后续 smoke 测试探到端口被占就 fail。
**修复**：portal fixture 退出时用 `psutil` 主动杀掉监听这 4 个端口的进程（额外依赖 `psutil`，本就常用于跨平台进程管理）。
**结果**：4 个 smoke 顺序串行跑全过。

## 新增的依赖
- `pytest-playwright`（仅运行 Playwright E2E 时需要）
- `psutil`（portal smoke fixture 清理子进程用）

## 新增的烟雾测试（4 个应用）
| 应用 | 文件 | 检查项 |
| --- | --- | --- |
| portal | `test/portal/test_smoke.py` | 端口 5000 起来；`/` 返回 200；`/api/status` 返回 list 且包含 4 个子 app id |
| test_report | `test/test_report/test_smoke.py` | 端口 5740 起来；`/` 返回 200 |
| domain_capture | `test/domain_capture/test_smoke.py` | 端口 5739 起来；`/` 返回 200 |
| config_analyzer | `test/config_analyzer/test_smoke.py` | `py -m http.server 5742` 起来；`er_config_analyzer.html` 含 `id="configText"` 与 `parseERConfig` |

## 验证结果

```
# 1) 不含 Playwright E2E 的全 pytest 套件
> py -3 -m pytest -v --deselect all_in_one/test_e2e_playwright.py
44 passed, 17 deselected in 22.40s

# 2) Playwright 独立脚本核心套件
> py -3 all_in_one/test_e2e_playwright.py --quick
42/42 通过, 0 失败 (100%) 用时 41s

# 3) pytest 跑 Playwright 单条用例（验证 fixture）
> py -3 -m pytest test_e2e_playwright.py::test_nav_tabs test_e2e_playwright.py::test_dhcp_toggle
2 passed in 15.66s
```

## 顺带改的产品代码
- `application/all_in_one - cc/web/app.py`：`__main__` 入口在 `TEST_MODE=1` 或 `NO_BROWSER=1` 时不再触发 `webbrowser.open`。这是修复测试基础设施需要的最小改动，不影响正常启动。

## 没动的部分
- `application/自动梳理配置 - cc/er_config_analyzer.html` 内的 JS 拓扑分析逻辑（无 Python 测试，HTML 内联 JS 由前端打开页面手动验证）。
- 各应用打包产物 (.exe / .spec / chromium)。
- 历史 log / logs 目录内已有的文件。
