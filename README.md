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

## 运行环境

- **客户使用（发布包）**：不需要安装 Python。解压 zip 后双击 `start_all.bat` 即可。
- **开发环境（源码运行）**：
  - OS：Windows 10 / 11
  - Python：3.11+（建议 3.13）
  - 依赖（最低）：
    ```bash
    py -3 -m pip install flask playwright dnspython python-docx paramiko Pillow
    ```
  - Playwright 浏览器（仅 `domain_capture` 和 E2E 测试需要）：
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
├── tools/
│   └── build_release.py         打包客户可分发 zip
├── dist/                        打包产物（gitignored）
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

## 发布新版本（下载通道）

客户拿到的是一个解压即用的 zip 包：解压一次得到 `帮你节省5分钟/` 文件夹，双击里面的 `start_all.bat` 就能跑起整套工具。

包内包含：源码 + 启动脚本 + `framework` + `runtime/python`（便携 Python + 运行时依赖）。
因此最终 zip 体积约 **70MB~80MB**（随依赖变动）。

包内不包含：`log/`、`application/test/`、`经历.md`、`plan/`、`.git/`、`editor_workspace/` 等开发期内容。

### 路径 1：本地打包（手动）

在项目根运行：

```bash
py -3 tools/build_release.py --version v1.0.0
```

产出 `dist/帮你节省5分钟-1.0.0.zip`。

补充：
- 不传 `--version` 时按 `git describe --tags --always --dirty` 推导，没 tag 时落到 `dev`
- `--list-only` 可以先看源码部分会被打进去的文件清单，**不实际写 zip**
- 构建时会自动执行 `tools/prepare_runtime.py`，把便携 Python 放进 zip 的 `runtime/python/`
- portal 首页（http://localhost:5000）侧栏底部会自动出现一个「下载完整应用」按钮，连到 `dist/` 里最新一份合法 zip。本地没有包时按钮自动隐藏

### 路径 2：GitHub Release（自动）

推一个 `v*` tag，CI 自动打包并发布到对应 Release：

```bash
git tag v1.0.0
git push origin v1.0.0
```

`.github/workflows/release.yml`（Windows runner）会做：
1. 跑 `tools/build_release.py --version v1.0.0`
2. 把 zip 上传为 workflow artifact
3. 把 zip 挂到 `v1.0.0` 这个 GitHub Release（Release notes 自动生成）

也可以在 GitHub Actions 页面手动触发 `release` workflow（带版本号），用于演练或试发；这种情况下只产出 artifact，不创建 git tag、不发 Release。

### 严谨性约束

按项目"不允许猜测"原则，portal 端的 `/api/download/latest` 只承认**zip 内含 `RELEASE_INFO.json`** 的合法包。把别的来路 zip 丢进 `dist/` 不会被识别——必须用 `tools/build_release.py` 产出。

---

## 开发须知

- **永远不要用兜底逻辑**：用户输入决定输出，输出必须可重现，不允许任何"猜一下"的行为。
- **修代码前先看 / 跑测试**：每个子应用的测试目录都是入口。
- **每次有动作要记一笔**：根目录 `log/` 和每个 app 自己的 `log/` 都存变动记录。

---

## License

私有项目。未授权请勿外传。
