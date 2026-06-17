# 帮你节省5分钟 — Linux/Docker 部署（Demo 版）

> **文档性质**：迁移蓝图（已完成）。实际状态见 README.md 和 `log/2026-06-17.md`。  
> **目标环境**：Linux 云服务器（4C4G ECS）+ Docker Compose 单容器部署  
> **端口**：5000（Portal）+ 5003（all_in_one）+ 9000（stats）

---

## 一、架构概览（当前实际）

```
┌─────────────────────────────────────────────────────┐
│              Docker Container                       │
│  ┌─────────────────────────────────────────────┐   │
│  │  Portal Flask (5000) — 统一入口 + 反向代理    │   │
│  └─────────────┬───────────────────────────────┘   │
│                │                                    │
│  ┌─────────────▼──────────┐  ┌─────────────────┐  │
│  │ all_in_one :5003       │  │ stats :9000     │  │
│  │ gunicorn 8 worker      │  │ 访问日志看板     │  │
│  │ (tkinter_stub 替代)    │  │                 │  │
│  └────────────────────────┘  └─────────────────┘  │
│                                                    │
│  Supervisor: portal + all_in_one + stats           │
│  （无 Xvfb — tkinter 已移除）                      │
│  Volumes:    持久化用户数据 / 日志                 │
└─────────────────────────────────────────────────────┘
```

**变更记录**（相对原始蓝图）：
- tkinter 已被 `tkinter_stub.py` 完全替代，Xvfb / DISPLAY 已移除
- all_in_one 从 `python app.py` 改为 gunicorn 8 worker 多进程并发
- 域名抓取/测试报告/配置梳理 已停用（supervisord 注释），仅保留配置生成 + stats
- 新增 stats 访问看板（:9000）
- 多用户并发安全：generate 从磁盘读模板，save/reset 只操作磁盘不改 ns

> ⚠️ 以下为原始迁移蓝图（2026-05 制定），保留作历史参考。部分内容（端口列表、tk/xvfb 安装、Xvfb 启动）已被上述变更取代，以 README.md 和 `log/` 为准。

---

## 二、Docker 部署

### 2.1 构建与启动

```bash
docker build -t fivemins .
docker compose up -d
```

### 2.2 端口映射

| 服务 | 容器内端口 | 宿主机端口 |
|------|-----------|------------|
| Portal | 5000 | 5000 |
| 域名抓取 | 5001 | 5001 |
| 测试报告 | 5002 | 5002 |
| 配置生成 | 5003 | 5003 |
| 配置梳理 | 5004 | 5004 |

### 2.3 常用命令

```bash
# 查看日志
docker compose logs -f

# 进入容器
docker exec -it fivemins-portal bash

# 重启
docker compose restart

# 升级（拉新代码 → 重建镜像 → 替换容器）
git pull
docker compose up -d --build

# 清理
docker compose down -v
```

---

## 三、裸机部署（不用 Docker 时）

### 3.1 系统依赖

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-tk xvfb \
  chromium-browser fonts-wqy-zenhei supervisor

# Playwright
pip install playwright
playwright install chromium
```

### 3.2 启动脚本

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Kill stale ports
for port in 5000 5001 5002 5003 5004; do
    fuser -k "${port}/tcp" 2>/dev/null || true
done

# Start Xvfb
Xvfb :99 -screen 0 1024x768x24 &
export DISPLAY=:99
export BROWSER=echo

# Start portal (foreground)
cd application/portal
python3 app.py
```

---

## 四、测试验证

### 4.1 端口检查

```bash
docker exec fivemins-portal ss -tlnp
# 应显示 5000-5004 全部在 LISTEN
```

### 4.2 功能检查

| 功能 | URL | 检查点 |
|------|-----|--------|
| Portal 首页 | `http://ECS_IP:5000/` | 标题正确、sidebar 4 个入口 |
| 配置生成 | `http://ECS_IP:5000/app/all_in_one/` | 页面加载、级联菜单可见 |
| 测试报告 | `http://ECS_IP:5000/app/test_report/` | 表单完整 |
| 域名抓取 | `http://ECS_IP:5000/app/domain_capture/` | 输入框 + 提交按钮 |
| 配置梳理 | `http://ECS_IP:5000/app/config_analyzer/` | HTML 渲染正常 |

---

## 五、数据持久化

| 数据类型 | 容器内路径 | Volume |
|----------|-----------|--------|
| 配置生成工作区 | `all_in_one - cc/data/editor_workspace` | portal-data |
| Portal 日志 | `portal/logs/` | portal-logs |

---

**文档版本**：v2.0 (Demo only)  
**编写日期**：2026-06-17
