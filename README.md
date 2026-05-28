# 帮你节省 5 分钟 · 网络配置工具套件

一组本地工具，把日常重复的网络运维工作从「敲 5 分钟」压成「点 1 下」。

[![tests](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml/badge.svg)](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml)

---

## 5 个子应用

| 子应用 | 端口 | 干啥的 |
| --- | :---: | --- |
| **portal** | 5000 | 统一入口，反向代理 + 监控其余 4 个子应用 |
| **all_in_one** （配置生成） | 5741 | Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN 一键配置生成；可视化模板编辑器 |
| **test_report** （自动做测试报告） | 5740 | 跑完测试用例后一键生成 Word 报告 |
| **domain_capture** （自动抓域名发2） | 5739 | 域名批量抓取、解析、聚合 |
| **config_analyzer** （自动梳理配置） | 5742 | 粘 VyOS / 华为 USG 配置进去自动出拓扑图 + 摘要 |

打开 `http://localhost:5000` 一个面板即可访问全部子应用。

---

## 启动

### 一键全启（推荐）

```bat
start_all.bat
```

这个脚本会做：
1. 杀掉 5000 / 5741 / 5740 / 5739 / 5742 上的旧进程
2. 拉起 portal（5000），portal 再依次拉起其余 4 个子应用
3. 浏览器自动打开 `http://localhost:5000`

按 `Ctrl+C` 退出，portal 会把所有子应用一并清理。

### 单独启某个子应用

```bat
application\all_in_one - cc\start_配置生成.bat
application\自动做测试报告 - cc\start_测试报告.bat
application\自动抓域名发2\start_域名抓取.bat
application\自动梳理配置 - cc\start_配置梳理.bat
```

---

## 环境

- **OS**：Windows 10 / 11（产品本体；CI 在 Ubuntu 上跑后端测试）
- **Python**：3.11+（开发用 3.13）
- **依赖**：见各子应用目录下的 `requirements.txt`；最低需要：
  ```bash
  py -3 -m pip install flask playwright dnspython python-docx paramiko Pillow
  ```
- **Playwright 浏览器**（仅 `domain_capture` 和 E2E 测试需要）：
  ```bash
  py -3 -m playwright install chromium
  ```

---

## 目录结构

```
.
├── application/
│   ├── portal/                  统一入口 + 反向代理 (5000)
│   ├── all_in_one - cc/         配置生成 (5741)
│   ├── 自动做测试报告 - cc/      测试报告 (5740)
│   ├── 自动抓域名发2/            域名抓取 (5739)
│   ├── 自动梳理配置 - cc/        配置梳理 (5742)
│   └── test/                    全部 Python 测试（按 app 分子目录）
│       ├── all_in_one/
│       ├── portal/
│       ├── test_report/
│       ├── domain_capture/
│       └── config_analyzer/
├── framework/                   各子应用共用的样式 / 文档
├── log/                         工作区级变动记录（.md）
├── plan/                        设计 / 重构计划文档
├── start_all.bat                一键启动
└── README.md
```

---

## 测试

测试统一放在 `application/test/`，按子应用分目录。

### 跑后端全量（不含浏览器自动化）

```bash
cd application\test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py
```

预期：**44 passed**（39 个 all_in_one 后端 + 5 个 4 应用烟雾测试），约 25 s。

### 跑 Playwright E2E

```bash
cd application\test\all_in_one
py -3 test_e2e_playwright.py --quick
```

预期：**42/42 通过**，约 45 s。

首次使用前需要安装：
```bash
py -3 -m pip install pytest-playwright psutil
py -3 -m playwright install chromium
```

### 只跑某个子应用

```bash
cd application\test
py -3 -m pytest portal              # portal 烟雾
py -3 -m pytest all_in_one          # all_in_one 全部后端
py -3 -m pytest all_in_one/test_hostname_all.py   # 某一组用例
```

---

## 端口规划

| 端口 | 用途 |
| :---: | --- |
| 5000 | portal（统一入口） |
| 5739 | domain_capture |
| 5740 | test_report |
| 5741 | all_in_one |
| 5742 | config_analyzer |

启动前会自动清理这 5 个端口上的旧进程，所以不用担心残留。

---

## 开发须知

- **永远不要用兜底逻辑**：用户输入决定输出，输出必须可重现，不允许任何"猜一下"的行为。
- **修代码前先看 / 跑测试**：每个子应用的测试目录都是入口。
- **每次有动作要记一笔**：根目录 `log/` 和每个 app 自己的 `log/` 都存变动记录。

---

## License

私有项目。未授权请勿外传。
