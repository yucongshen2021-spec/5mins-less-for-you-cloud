# 帮你节省 5 分钟 · 网络配置工具套件（Demo 版）

一组本地工具，把日常重复的网络运维工作从「敲 5 分钟」压成「点 1 下」。

[![tests](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml/badge.svg)](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml)

---

## 版本说明

项目为 **纯 Demo 版本**，端口统一使用 5000 系列（Portal 5000 + 4 个子应用 5001-5004）。不再区分 Demo/Release 双版本。

| 服务 | 端口 |
|------|------|
| **Portal** | 5000 |
| **域名抓取** | 5001 |
| **测试报告** | 5002 |
| **配置生成** | 5003 |
| **配置梳理** | 5004 |

---

## 4 个子应用

| 子应用 | 功能 |
|--------|------|
| **portal** | 统一入口，反向代理，状态监控 |
| **配置生成** | Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN 一键生成；可视化模板编辑器 |
| **测试报告** | 跑完测试用例后一键生成 Word 报告 |
| **域名抓取** | 域名批量抓取、DNS CNAME 链路追踪、CDN 识别 |
| **配置梳理** | 粘贴 VyOS / 华为 USG 配置，自动生成拓扑图 + 摘要 |

打开 portal 统一入口即可访问全部子应用。点击右上角 **"?"** 查看使用教程。

---

## 启动

```bash
docker compose up -d        # 一键启动，打开 http://localhost:5000
```

停止：`docker compose down`。容器内由 supervisord 统一拉起 portal 及各子应用，停止容器即全部清理。

---

## 运行环境

- **部署环境**：Linux 云服务器（ECS）+ Docker Compose 单容器部署，Python 3.13
  ```bash
  docker build -t fivemins .
  docker compose up -d
  ```
- **裸机开发**：Linux / Windows 10/11，Python 3.13
  ```bash
  pip install -r requirements.txt
  playwright install chromium          # domain_capture + E2E 测试需要
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
├── docker/                          supervisord 配置
├── docker-compose.yml               单容器编排
├── Dockerfile
├── .github/workflows/
│   └── test.yml                     CI 测试（main 分支）
├── log/                             变动记录
├── plan/                            设计文档
└── README.md
```

---

## 测试

### 全量后端测试

```bash
cd application/test
python -m pytest --deselect all_in_one/test_e2e_playwright.py
```

### Playwright 浏览器 E2E

```bash
cd application/test/all_in_one
python test_e2e_playwright.py --quick
```

预期：**42/42 通过**

```bash
pip install pytest-playwright psutil
playwright install chromium
```

---

## 开发须知

- **永远不要用兜底逻辑**：输出必须可重现，不允许猜测
- **TDD**：先写测试，再写实现
- **每次有动作记一笔**：`log/` 目录存变动记录

---

## License

私有项目。未授权请勿外传。
