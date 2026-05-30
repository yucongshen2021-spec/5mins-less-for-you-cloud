# Demo / Release 双版本分离 — 设计文档

> 2026-05-30

## 概述

将应用拆分为 demo 版（测试先行，永远最新）和 release 版（稳定，客户使用）。

## 分支策略

```
main ────────────→  demo 版 (5000-5004)
  │  (测试通过后 merge)
  ↓
release ─────────→  release 版 (6000-6004)
```

## 端口

| 应用 | Demo (main) | Release (release) |
|------|:-----------:|:-----------------:|
| portal | 5000 | 6000 |
| 域名抓取 | 5001 | 6001 |
| 测试报告 | 5002 | 6002 |
| 配置生成 | 5003 | 6003 |
| 配置梳理 | 5004 | 6004 |

## 功能差异

### Demo 版

**有：**
- 侧栏 "下载完整应用" 按钮（`/api/download/latest`、`/download/latest.zip`）
- `/api/status`
- 4 个子应用代理

**没有：**
- 更新横幅（`/api/update/check`、`/api/update/manifest` 端点不存在）
- "在线升级" 按钮
- `update_check.py`、`upgrade.py` 不被加载
- `update_config.json` 的 mirror_url 留空

### Release 版

**有：**
- 更新横幅 + 在线升级（`/api/update/check`、`/api/update/manifest`、`/api/update/upgrade`、`/api/shutdown`）
- `/api/status`
- 4 个子应用代理

**没有：**
- "下载完整应用" 按钮（`/api/download/latest` 端点不存在或始终返回 unavailable）

**update_config.json** 内 mirror_url 指向外部可达地址（打包时通过 `--mirror-url` 注入）。

## GitHub Actions

### test.yml — 仅 main 分支

触发：push/PR to `main`
- 跑 demo 版测试（端口 5000-5004）
- 不打包

### release.yml — 仅 release 分支

触发：tag `v*` on `release` + workflow_dispatch
- 跑 release 版测试（端口 6000-6004）
- 打包 `build_release.py`
- 发布 GitHub Release

## 需要修改的文件

### 创建

- 两份完整代码分别在 `main` 和 `release` 分支
- 两份 GitHub Actions workflow

### 修改（每个分支上）

| 文件 | demo 版 | release 版 |
|------|---------|------------|
| `application/portal/app.py` | 去掉 update_check/upgrade 导入和端点；端口 5000 | 去掉 download 端点；端口 6000 |
| `application/portal/process_manager.py` | 端口 5001-5004 | 端口 6001-6004 |
| `application/portal/templates/index.html` | 去掉更新横幅/"在线升级"；保留下载按钮 | 去掉下载按钮；保留更新横幅/"在线升级" |
| `application/portal/update_config.json` | mirror_url 为空 | mirror_url 预置外部地址 |
| `start_all.bat` | 端口 5000-5004 | 端口 6000-6004 |
| `application/test/` | 端口指向 5000-5004 | 端口指向 6000-6004 |
| `.github/workflows/test.yml` | 仅 main 触发，端口 5000-5004 | — |
| `.github/workflows/release.yml` | — | 仅 release 触发，端口 6000-6004 |

### 不需要改的

- `application/portal/proxy.py`（无关端口，通过 port_map 查找）
- `application/portal/upgrade.py`（release 版保留，demo 版删除）
- `application/portal/update_check.py`（release 版保留，demo 版删除）
- `tools/build_release.py`（两版通用）
- 4 个子应用代码（端口从配置传入，无需改逻辑）

## 测试

- Demo 版：pytest 全部指向 5000-5004
- Release 版：pytest 全部指向 6000-6004
- Playwright E2E：端口对应
- simulate_customer.py：端口对应
