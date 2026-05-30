# 帮你节省 5 分钟 · 网络配置工具套件

一组本地工具，把日常重复的网络运维工作从「敲 5 分钟」压成「点 1 下」。

[![tests](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml/badge.svg)](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml)

---

## 双版本架构

项目分两个版本，通过 Git 分支管理：

| | Demo 版（`main`） | Release 版（`release`） |
|---|---|---|
| **定位** | 测试先行，永远最新 | 稳定交付，客户使用 |
| **Portal** | 5000 | 6000 |
| **域名抓取** | 5001 | 6001 |
| **测试报告** | 5002 | 6002 |
| **配置生成** | 5003 | 6003 |
| **配置梳理** | 5004 | 6004 |
| **下载按钮** | 有 | 无 |
| **更新横幅** | 无 | 有 |
| **在线升级** | 无 | 有 |
| **CI 测试** | test.yml | release.yml（含打包发布） |

两版端口互不冲突，可同时启动。

### 日常流程

```
main (demo)                    release (交付)
─────                          ─────
开发新功能、写测试              git merge main
测试通过                       测试通过
                              git tag v1.0.0 → CI 自动打包发布
                              客户通过外部 IP 检测更新 + 在线升级
```

---

## 5 个子应用

| 子应用 | 功能 |
|---|---|
| **portal** | 统一入口，反向代理，状态监控，更新管理 |
| **配置生成** | Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN 一键生成；可视化模板编辑器 |
| **测试报告** | 跑完测试用例后一键生成 Word 报告 |
| **域名抓取** | 域名批量抓取、DNS CNAME 链路追踪、CDN 识别 |
| **配置梳理** | 粘贴 VyOS / 华为 USG 配置，自动生成拓扑图 + 摘要 |

打开 portal 统一入口即可访问全部子应用。点击右上角 **"?"** 查看使用教程。

---

## 启动

### Demo 版

```bat
start_all.bat            # 一键启动，打开 http://localhost:5000
```

### Release 版

```bat
start_all.bat            # 一键启动，打开 http://localhost:6000
```

Ctrl+C 退出，portal 会把所有子应用一并清理。

---

## 运行环境

- **客户使用（发布包）**：不需要安装 Python。解压 zip 后双击 `start_all.bat` 即可。
- **开发环境**：Windows 10/11，Python 3.13
  ```bash
  py -3 -m pip install flask playwright dnspython python-docx paramiko Pillow
  py -3 -m playwright install chromium          # domain_capture + E2E 测试需要
  ```

---

## 目录结构

```
.
├── application/
│   ├── portal/                      统一入口 + 反向代理
│   ├── all_in_one - cc/             配置生成
│   ├── 自动做测试报告 - cc/          测试报告
│   ├── 自动抓域名发2/                域名抓取
│   ├── 自动梳理配置 - cc/            配置梳理
│   └── test/                        全部测试（按 app 分目录）
├── tools/
│   ├── build_release.py             打包客户可分发 zip
│   ├── prepare_runtime.py           准备便携 Python 运行时
│   ├── publish_manifest.py          生成更新清单
│   └── simulate_customer.py         模拟客户更新检测
├── .github/workflows/
│   ├── test.yml                     CI 测试（main 分支）
│   └── release.yml                  CI 测试 + 打包发布（release 分支）
├── log/                             变动记录
├── plan/                            设计文档
├── dist/                            打包产物（gitignored）
├── start_all.bat                    一键启动
└── README.md
```

---

## 测试

### 全量后端测试

```bash
cd application\test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py
```

- Demo 版预期：**50 passed**（39 all_in_one + 11 smoke 含功能开关）
- Release 版预期：**49 passed**（同上，减 1 个下载端点测试）

### Playwright 浏览器 E2E

```bash
cd application\test\all_in_one
py -3 test_e2e_playwright.py --quick
```

预期：**42/42 通过**

```bash
py -3 -m pip install pytest-playwright psutil
py -3 -m playwright install chromium
```

### 版本更新仿真

```bash
py -3 tools\simulate_customer.py
```

模拟 6 个场景：版本相同、有新版本、服务器宕机、客户版本更高、缓存生效等。预期 **24/24 通过**。

---

## 在线更新（Release 版）

### 客户端

Release 版启动后自动检查更新。检测到新版本时顶部出现橙色横幅，点击**「在线升级」**按钮自动下载、替换文件、重启 portal。用户数据不受影响。

### 服务端

1. 把新 zip 放到 `dist/` 目录
2. `/api/update/manifest` 自动识别最新 zip 并返回版本信息
3. 无需重启 portal

### 打包时预置更新源

```bash
py -3 tools/build_release.py --version v1.0.0 --mirror-url http://外部IP:6000/api/update/manifest
```

客户包内的 `update_config.json` 会自动写入 `mirror_url`，解压即用。

---

## 发布新版本

### 本地打包

```bash
py -3 tools/build_release.py --version v1.0.0
```

产出 `dist/帮你节省5分钟-1.0.0.zip`（约 70-80 MB，含便携 Python 运行时）。

更多选项：
- `--no-runtime`：不打包 Python 运行时，仅源码（约 3 MB，本地测试用）
- `--mirror-url <url>`：注入更新源地址到客户包
- `--list-only`：预览文件清单，不实际写 zip

### GitHub Release（自动）

在 release 分支推 tag：

```bash
git checkout release
git tag v1.0.0
git push origin v1.0.0
```

CI 自动跑测试 → 打包 → 发布 GitHub Release。

---

## 开发须知

- **永远不要用兜底逻辑**：输出必须可重现，不允许猜测
- **TDD**：先写测试，再写实现
- **每次有动作记一笔**：`log/` 目录存变动记录
- **审查意见不进客户包**：`审查意见-*.md` 已在 build_release.py 排除

---

## License

私有项目。未授权请勿外传。
