# 帮你节省 5 分钟 · 网络配置工具套件（Demo 版）

一组本地工具，把日常重复的网络运维工作从「敲 5 分钟」压成「点 1 下」。

[![tests](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml/badge.svg)](https://github.com/yucongshen2021-spec/5mins-less-for-you/actions/workflows/test.yml)

---

## 版本说明

项目为 **纯 Demo 版本**，端口统一使用 5000 系列。不再区分 Demo/Release 双版本。

当前实际启动的服务（supervisord 管理）：

| 服务 | 端口 | 说明 |
|------|------|------|
| **Portal** | 5000 | 统一入口，反向代理，状态监控 |
| **配置生成（all_in_one）** | 5003 | gunicorn 8 worker 多进程并发 |
| **stats 访问看板** | 9000 | 访问日志统计仪表盘 |

域名抓取（5001）、测试报告（5002）、配置梳理（5004）当前已停用（代码保留，supervisord 注释），恢复时取消 `docker/supervisord.conf` 对应段注释即可。

---

## 核心应用：配置生成（all_in_one）

Epoch FastIP / USG FastIP / Epoch MPLS / AR SD-WAN / AR 传统组网 一键生成；可视化模板编辑器。

**多并发架构**：gunicorn 8 worker 进程隔离，每个 worker 独立加载业务模块，worker 间天然并发。tkinter 已被 `tkinter_stub.py` 完全替代，**无需 Xvfb / DISPLAY**，无线程安全约束。

打开 portal 统一入口即可访问全部子应用。点击右上角 **"?"** 查看使用教程。

---

## 启动

```bash
docker compose up -d        # 一键启动，打开 http://localhost:5000
```

停止：`docker compose down`。容器内由 supervisord 统一拉起 portal + all_in_one（gunicorn）+ stats，停止容器即全部清理。

### 测试环境（8000 端口）

所有改动先在 8000 端口测试，通过后再重建正式 5000 容器：

```bash
sudo docker-compose -f docker-compose.test.yml up -d --build   # 构建+启动
# 访问 http://localhost:8000（Portal）、http://localhost:8001（stats）
sudo docker-compose -f docker-compose.test.yml down            # 停止
```

---

## 运行环境

- **部署环境**：Linux 云服务器（4C4G）+ Docker Compose 单容器部署，Python 3.11
  ```bash
  docker build -t fivemins .
  docker compose up -d
  ```
- **裸机开发**：Linux / Windows 10/11，Python 3.11+
  ```bash
  pip install -r requirements.txt
  # 无需 tkinter / Xvfb / DISPLAY（已用 tkinter_stub 替代）
  playwright install chromium          # 仅 domain_capture + E2E 测试需要
  ```

---

## 目录结构

```
.
├── application/
│   ├── portal/                      统一入口 + 反向代理 :5000
│   ├── all_in_one - cc/             配置生成 :5003（gunicorn 8 worker）
│   │   ├── web/
│   │   │   ├── app.py               Flask 后端
│   │   │   ├── wsgi.py              gunicorn 入口
│   │   │   ├── gunicorn_conf.py     gunicorn 配置（8 worker）
│   │   │   └── tkinter_stub.py      tkinter 替代模块（纯 Python mock）
│   │   ├── src/                     业务模块（6 个厂商配置生成器）
│   │   └── data/                    模板数据 + 用户配置
│   ├── stats/                       访问日志看板 :9000
│   ├── 自动做测试报告 - cc/          测试报告（停用）
│   ├── 自动抓域名发2/                域名抓取（停用）
│   ├── 自动梳理配置 - cc/            配置梳理（停用）
│   ├── common/                      共享模块（stats_db）
│   └── test/                        全部测试（含 blackbox_8000 黑箱）
├── docker/
│   └── supervisord.conf             进程编排（portal + all_in_one + stats）
├── docker-compose.yml               正式编排（5000 + 9000）
├── docker-compose.test.yml          测试编排（8000→5000, 8001→9000）
├── Dockerfile
├── .github/workflows/test.yml       CI 测试（main 分支）
├── log/                             变动记录
├── plan/                            设计文档
└── README.md
```

---

## 测试

### 全量后端测试（test_client，无需容器）

```bash
cd application/test
python -m pytest --deselect all_in_one/test_e2e_playwright.py
```

预期：**170+ passed**（无 tkinter / 无 DISPLAY / 无 Xvfb）

### 8000 端口黑箱测试（需启动测试容器）

```bash
cd application/test
python -m pytest blackbox_8000/ -q
```

### 并发验证（8 worker，无串号）

```bash
# 启动测试容器后，并发发 8 个不同参数的 generate 请求
python -c "
import urllib.request, json, concurrent.futures
# ... 见 log/2026-06-17.md 中的测试脚本
"
```

### Playwright 浏览器 E2E

```bash
cd application/test/all_in_one
python test_e2e_playwright.py --quick
```

```bash
pip install pytest-playwright psutil
playwright install chromium
```

---

## 开发须知

- **永远不要用兜底逻辑**：输出必须可重现，不允许猜测
- **TDD**：先写测试，再写实现
- **每次有动作记一笔**：`log/` 目录存变动记录
- **多并发安全**：generate 从磁盘读模板（`_get_effective_template`），save/reset 只操作磁盘不改 ns，避免并发竞态
- **tkinter 已移除**：业务模块用 `tkinter_stub.py` 替代，不要恢复 `import tkinter` 或添加 Xvfb 依赖

---

## License

私有项目。未授权请勿外传。
