# 80 端口连通性测试页

独立的连通性测试服务，与业务系统（5000 / 8000 / 9000）**完全隔离**，仅用于验证网络链路可达性。

## 功能

| 路径 | 说明 |
|------|------|
| `/` | 静态测试页（展示访问来源 IP、时间等） |
| `/health` | 返回 `ok`（供探活 / 监控） |
| `/ip` | 回显请求方 IP（`X-Real-IP` → `X-Forwarded-For` → 直连地址） |

无业务逻辑、无数据库、无登录，不依赖正式镜像。

## 运行参数（当前生产实际配置）

- 镜像：`python:3.11-slim-bookworm`（官方基础镜像，与业务镜像无关）
- 命令：`python3 /srv/server.py`，工作目录 `/srv`
- 挂载：`/opt/fivemins/port80-test` → `/srv`（改 `index.html` 即改即生效，无需重启）
- 重启策略：`unless-stopped`
- 端口：`0.0.0.0:80 → 80`

## 重建命令（独立容器，不在任何 compose 内）

```bash
sudo docker rm -f fivemins-port80-test 2>/dev/null
sudo docker run -d --name fivemins-port80-test \
  --restart unless-stopped \
  -p 80:80 \
  -v /opt/fivemins/port80-test:/srv \
  -w /srv \
  python:3.11-slim-bookworm \
  python3 /srv/server.py
```

## 说明

- 容器停机不影响 5000 / 9000 的任何功能；
- 反向代理 / CDN 指向 80 端口时，`/ip` 可回显真实来源 IP，用于确认链路；
- 该目录代码已纳入 git；容器本身不写入 Dockerfile / docker-compose.yml（刻意保持隔离）。
