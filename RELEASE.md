# Release Process — 帮你节省5分钟

## 一键发版

```powershell
git checkout release
py tools/release.py <version>
```

Example: `py tools/release.py 1.1.8`

## 本地测试（不推送）

```powershell
py tools/release.py <version> --no-push
```

## 全量测试

```powershell
# 应用功能测试
py -m pytest application/test/ -v --ignore=application/test/config_analyzer/test_e2e_playwright.py --ignore=application/test/all_in_one/test_e2e_playwright.py

# Portal 更新 UI 测试（Playwright 点击真实按钮）
py -m pytest application/test/portal/test_update_ui_playwright.py -v

# 完整客户模拟测试（解压→启动→检测更新→验证 UI）
py application/test/portal/test_customer_full.py

# 构建后 zip 校验
py tools/_verify_zip.py dist/帮你节省5分钟-<version>.zip <version>
```

## 启动服务

```powershell
# Demo 版（端口 5000，自动启动 mirror 8000）
py application/portal/app.py

# Release 版（端口 7000，不启动 mirror）
$env:RELEASE_MODE = "1"
py application/portal/app.py
```

## Mirror 服务

```powershell
# 手动启动 mirror（Demo 版自动启动，Release 需手动）
py tools/serve_mirror.py --port 8000 --dist dist

# 检查 mirror
curl http://127.0.0.1:8000/api/update/manifest
```

## 发布前检查

- [ ] `py -m pytest application/test/ -v` 通过
- [ ] `py application/test/portal/test_customer_full.py` 通过
- [ ] `git branch` 在 `release`
- [ ] `dist/` 有旧版 zip 供客户模拟测试

## 客户更新地址

| 优先级 | 地址 |
|--------|------|
| 主 | `http://192.168.72.219:8000/api/update/manifest` |
| 备 | `http://192.168.5.10:8000/api/update/manifest` |

## 架构

```
dev machine
├── main branch → demo portal (5000) + auto mirror (8000)
├── release branch → py tools/release.py → dist/帮你节省5分钟-<ver>.zip
│
customer machine
└── extracted zip → release portal (7000)
    ├── auto check (5s) → mirror
    ├── manual check button (sidebar)
    └── upgrade button → download → bat → restart
```
