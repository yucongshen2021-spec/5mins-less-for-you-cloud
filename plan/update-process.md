# 更新模块流程固化 — 帮你节省5分钟

> **目标：** 固化版本更新流程的每一个步骤、每一个组件、每一个验证点。以后每次更新都按此文档执行，确保零差错。
>
> **原则：** 更新模块和业务模块严格分离。更新只依赖 mirror + update_check + upgrade 三个组件，不触碰任何业务代码。

---

## 目录

1. [架构概览](#1-架构概览)
2. [组件清单](#2-组件清单)
3. [更新检查流程](#3-更新检查流程)
4. [升级执行流程](#4-升级执行流程)
5. [Mirror 服务](#5-mirror-服务)
6. [构建 & 配置注入](#6-构建--配置注入)
7. [端到端验证](#7-端到端验证)
8. [错误处理 & 恢复](#8-错误处理--恢复)
9. [发版 Checklist](#9-发版-checklist)
10. [历史错误 & 防范](#10-历史错误--防范)

---

## 1. 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                        DEV MACHINE                               │
│                                                                   │
│  main branch                                                     │
│  ├── portal (5000) ← demo 版                                     │
│  ├── mirror (8000)  ← 自动启动（serve_mirror.py）                 │
│  └── dist/*.zip     ← 构建产物                                    │
│                                                                   │
│  release branch                                                   │
│  ├── py tools/release.py <version>                                │
│  └── dist/帮你节省5分钟-<version>.zip                              │
│                                                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                   │
│                     CUSTOMER MACHINE                              │
│                                                                   │
│  release portal (7000) ← 从 zip 解压启动                          │
│  ├── 5s 后自动检查更新  ──────────┐                                │
│  ├── 手动检查按钮       ──────────┤                                │
│  └── 每小时定时检查     ──────────┤                                │
│                                   │                                │
│                                   ▼                                │
│  mirror (8000) ← 独立服务（开发机上运行）                          │
│  ├── GET /api/update/manifest → {version, download_url, ...}     │
│  └── GET /api/update/download/latest.zip → 最新 zip 下载          │
│                                                                   │
└─────────────────────────────────────────────────────────────────┘
```

### 关键约束

1. **Mirror 是独立服务** — 独占端口 8000，由开发机上的 `tools/serve_mirror.py` 运行
2. **客户 portal 不是 mirror** — 客户 zip 不含 dist/，不提供 manifest 端点
3. **客户是 mirror 的 consumer** — 只消费更新信息，不提供更新信息
4. **Demo portal 自动启动 mirror** — 开发便利性
5. **Release portal 不启动 mirror** — 客户不需要

---

## 2. 组件清单

### 2.1 核心组件

| 组件 | 文件 | 职责 | 部署位置 |
|------|------|------|---------|
| **更新检查** | `application/portal/update_check.py` | 多源版本检查 + 缓存 | 客户 zip 内 |
| **升级执行** | `application/portal/upgrade.py` | 下载 → 解压 → 替换 → 重启 | 客户 zip 内 |
| **升级脚本** | `UPDATE_BAT_TEMPLATE` (in upgrade.py) | 6 步自动化升级 bat | 升级时生成 |
| **配置** | `application/portal/update_config.json` | mirror URL 配置 | 客户 zip 内（构建时注入） |
| **缓存** | `application/portal/.update_cache.json` | 检查结果缓存 | 客户 zip 内（运行时生成） |
| **版本信息** | `RELEASE_INFO.json` | 当前运行版本 | zip 解压根（构建时写入） |

### 2.2 服务端组件

| 组件 | 文件 | 职责 | 部署位置 |
|------|------|------|---------|
| **Mirror 服务** | `tools/serve_mirror.py` | 提供 manifest + zip 下载 | 开发机 :8000 |
| **构建脚本** | `tools/build_release.py` | 打包 + 注入配置 | 开发机 |
| **发版脚本** | `tools/release.py` | 一键发版 | 开发机 |

### 2.3 前端组件（Release 版）

| 组件 | 位置 | 功能 |
|------|------|------|
| **upgradeBtn** | 侧栏底部 | 5 态更新按钮 |
| **btnCheckUpdate** | 侧栏底部 | 手动检查版本 |
| **updateBanner** | 页面顶部 | 更新横幅（有新版本时） |
| **updateBannerUpgrade** | 横幅内 | 一键升级按钮 |

---

## 3. 更新检查流程

### 3.1 触发方式

| 触发方式 | 频率 | force 参数 |
|---------|------|:----------:|
| 页面加载后 | 5s 后首次 | `force=1` |
| 定时器 | 每小时 | `force=0` |
| 手动按钮 | 点击时 | `force=1` |
| API 调用 | 外部调用 | 可选 |

### 3.2 数据流

```
checkForUpdate(force)
  │
  ├─→ GET /api/update/check?force={0|1}
  │     │
  │     ├─→ load_config()                    读取 update_config.json
  │     │     ├─→ mirror_urls: [...]         主备双源
  │     │     ├─→ timeout_seconds: 5         单源超时
  │     │     └─→ cache_ttl_seconds: 3600   缓存有效期
  │     │
  │     ├─→ force=0 → 读缓存（内存 + 磁盘）  未过期直接返回
  │     │
  │     ├─→ force=1 → 跳过缓存
  │     │
  │     ├─→ get_local_version()              读 RELEASE_INFO.json
  │     │
  │     ├─→ 遍历 mirror_urls（按顺序）
  │     │     ├─→ fetch_mirror_manifest(url)  每个源 GET → JSON
  │     │     │     ├─→ 成功 → 比较版本
  │     │     │     └─→ 失败 → 记录 error → 尝试下一个
  │     │     └─→ 所有源失败 → status: network_error
  │     │
  │     ├─→ compare_versions(local, remote)   按语义化版本比较
  │     │     ├─→ lp < rp → comparison: older
  │     │     ├─→ lp == rp → comparison: same
  │     │     ├─→ lp > rp → comparison: newer
  │     │     └─→ 无法解析 → comparison: incomparable
  │     │
  │     └─→ 返回 JSON → 写缓存
  │
  ├─→ applyCheckResult(info)                 更新 UI 状态
  │     ├─→ has_update + download_url → upgradeBtn: is-available
  │     ├─→ same/newer → upgradeBtn: is-up-to-date
  │     └─→ network_error/config_error → upgradeBtn: is-error
  │
  └─→ has_update=true → showUpdateBanner()   显示横幅
```

### 3.3 返回结构（完整）

```json
{
  "status": "ok" | "network_error" | "config_error",
  "local_version": "1.2.3" | null,
  "remote_version": "1.3.0" | null,
  "comparison": "older" | "same" | "newer" | "incomparable",
  "has_update": true | false,
  "release_url": "https://...",
  "download_url": "https://..." | null,
  "source": "mirror",
  "errors": ["mirror: URLError: ..."],
  "checked_at": 1717620000,
  "from_cache": true | false,
  "cache_age_seconds": 0
}
```

### 3.4 状态语义

| status | 含义 | upgradeBtn 状态 |
|--------|------|----------------|
| `ok` + `has_update: true` | 有新版本可用 | `is-available`（橙色，可点击升级） |
| `ok` + `comparison: same` | 已是最新 | `is-up-to-date`（灰色，不可点击） |
| `ok` + `comparison: newer` | 本地比远端新（开发环境） | `is-up-to-date`（灰色，不可点击） |
| `ok` + `comparison: incomparable` | 版本号格式无法比较 | `is-error` |
| `network_error` | 所有 mirror 源不可达 | `is-error`（可点击重试） |
| `config_error` | 无 mirror_url 配置 | `is-error`（可点击重试） |

---

## 4. 升级执行流程

### 4.1 触发方式

1. **侧栏按钮** — upgradeBtn 在 `is-available` 状态时点击
2. **横幅按钮** — "一键升级" 按钮点击

### 4.2 完整升级步骤

```
performUpgrade(download_url)
  │
  ├─→ [1] 下载 zip
  │     ├─→ URL 编码（支持中文）
  │     ├─→ 下载到 <parent>/__update__.zip
  │     ├─→ 超时: 120s
  │     └─→ 失败: 返回 {ok: false, stage: "download"}
  │
  ├─→ [2] 验证 zip
  │     ├─→ 检查 < 100KB → 太小的文件拒绝
  │     ├─→ 检查 RELEASE_INFO.json 存在
  │     └─→ 失败: 返回 {ok: false, stage: "verify"}
  │
  ├─→ [3] 扫描冲突
  │     └─→ 检查 protected paths（editor_workspace 等）
  │
  ├─→ [4] 生成 update.bat
  │     └─→ 写入 <parent>/__update__.bat
  │
  ├─→ [5] 启动 update.bat
  │     └─→ cmd /c start "5mins-tools Online Upgrade" <bat>
  │
  └─→ [6] Portal 关闭
        └─→ fetch /api/shutdown (2 秒延迟后)
```

### 4.3 update.bat 6 步流程

```
[1/6] 等待 portal 退出
  → 轮询端口 7000-7004 的 LISTENING 状态
  → 最多等 20 秒

[2/6] 强杀残留端口
  → netstat -ano → taskkill /F 每个残留进程
  → 等 3 秒

[3/6] 备份用户数据
  → 备份 editor_workspace/ → __ws_backup__/
  → 备份 user_init_placeholders.json
  → 备份 .update_cache.json

[4/6] 解压 + 复制新版本
  → powershell Expand-Archive __update__.zip → __update_tmp__
  → robocopy 复制到 BUNDLE 目录
  → 失败自动重试一次
  → 清理临时文件

[5/6] 恢复用户数据
  → 从 __ws_backup__/ 恢复所有备份项
  → 清理备份目录

[6/6] 重启 portal
  → endlocal → 保存 BUNDLE 路径 → start start_all.bat
  → exit
```

### 4.4 保护的用户数据

| 路径 | 内容 | 备份方式 |
|------|------|---------|
| `application/all_in_one - cc/data/editor_workspace/` | 模板编辑器用户工作区 | robocopy 全量 |
| `user_init_placeholders.json` | 用户初始默认值 | copy |
| `.update_cache.json` | 更新检查缓存 | copy |

---

## 5. Mirror 服务

### 5.1 启动命令

```powershell
# 标准启动
py tools/serve_mirror.py --port 8000 --dist dist

# 指定 dist 目录
py tools/serve_mirror.py --port 8000 --dist <path/to/dist>
```

### 5.2 端点

| 端点 | 返回 | 说明 |
|------|------|------|
| `GET /api/update/manifest` | `{"version": "1.2.3", "release_url": "...", "download_url": "..."}` | 最新 zip 元数据 |
| `GET /api/update/download/latest.zip` | 最新 zip 文件（binary） | 动态选择最新 mtime 的 zip |

### 5.3 Mirror 配置

| 优先级 | 地址 | 用途 |
|:------:|------|------|
| 主 | `http://192.168.72.219:8000/api/update/manifest` | 主 mirror |
| 备 | `http://192.168.5.10:8000/api/update/manifest` | 备用 mirror |

### 5.4 Mirror 规则

1. **Mirror 必须在客户可访问的 IP 上运行**
2. **Mirror 端口 8000 不能被其他进程占用**
3. **dist/ 目录必须存在且有合法 zip**
4. **Demo 版启动自动启动 mirror，Release 版需手动启动**
5. **客户 portal 不是 mirror** — 不存在 `/api/update/manifest` 路由

---

## 6. 构建 & 配置注入

### 6.1 构建命令

```powershell
# 完整发版（构建 + 提交 + 推送 + 验证）
git checkout release
py tools/release.py <version>

# 仅本地构建（不推送）
py tools/release.py <version> --no-push
```

### 6.2 构建参数

| 参数 | 必需 | 说明 |
|------|:----:|------|
| `version` | ✓ | 版本号，如 `1.2.3` |
| `--mirror-url` | ✓ | mirror manifest URL（可多次指定，第一个为主源） |
| `--no-push` | — | 跳过 git push |

### 6.3 配置注入

构建时写入以下文件到 zip：

| 文件 | 来源 | 内容 |
|------|------|------|
| `RELEASE_INFO.json` | 构建时生成 | `{"version": "1.2.3", "built_at": "...", ...}` |
| `application/portal/update_config.json` | 构建时注入 | `{"mirror_urls": ["http://...", "http://..."], ...}` |

### 6.4 端口替换

构建时执行端口替换（`application/portal/_RELEASE_PORT_FILES` 中列出的文件）：

| 替换 | 文件 |
|------|------|
| `5000` → `7000` | app.py, process_manager.py, start_all.bat |
| `5001` → `7001` | process_manager.py |
| `5002` → `7002` | process_manager.py |
| `5003` → `7003` | process_manager.py |
| `5004` → `7004` | process_manager.py |

**关键约束：使用 `re.sub(r"\b" + old + r"\b", new, text)` 做单词边界匹配，避免 `chcp 65001` → `chcp 67001` 误伤。**

### 6.5 构建排除

| 排除 | 原因 |
|------|------|
| `runtime/` (目录) | 由 `collect_runtime_files` 单独收集 |
| `*.pyc`, `__pycache__/` | 字节码缓存 |
| `*.zip`, `*.7z` | 旧构建产物 |
| `.git/`, `.github/` | 版本控制 |
| `RELEASE_INFO.json` (根文件) | 构建末尾 `writestr` 写入，不在源码 walk |
| `application/portal/*.log` | 日志文件 |
| `application/portal/.update_cache.json` | 缓存文件 |
| `plan/`, `log/` | 文档目录 |
| `DESIGN.md`, `README.md`, `CLAUDE.md`, `RELEASE.md`, `AGENTS.md` | 文档文件 |
| `tools/` (目录) | 开发工具 |
| `*.mp4`, `*.mkv`, `*.webm` | 视频文件 |
| 以 `test_` 开头的目录 | 测试目录 |
| `*.docx` (仅 `application/自动做测试报告/data/*/screenshots/`) | 保留合法模板 |

---

## 7. 端到端验证

### 7.1 完整验证流程（发版前必须通过）

```powershell
# 步骤 1: 构建两个版本（旧版 + 新版）
git checkout release
py tools/release.py 1.0.5 --no-push    # 旧版
# （修改版本号...）
py tools/release.py 1.0.6 --no-push    # 新版

# 步骤 2: 启动 mirror（提供更新源）
py tools/serve_mirror.py --port 8000

# 步骤 3: 解压旧版（模拟客户环境）
# 解压 dist/帮你节省5分钟-1.0.5.zip → temp/
# 修改 temp/application/portal/update_config.json → mirror_urls 指向 127.0.0.1:8000

# 步骤 4: 用包内 Python 启动旧版 portal
temp/runtime/python/python.exe application/portal/app.py

# 步骤 5: 验证更新检查
curl http://localhost:7000/api/update/check?force=1
# → {"status": "ok", "has_update": true, "remote_version": "1.0.6", ...}

# 步骤 6: Playwright 打开 http://localhost:7000
# → 横幅显示 "v1.0.6"
# → upgradeBtn 变为 is-available 状态
# → 零 console 错误

# 步骤 7: 执行升级（可选 — 会替换文件）
curl -X POST http://localhost:7000/api/update/upgrade \
  -H "Content-Type: application/json" \
  -d '{"download_url": "http://127.0.0.1:8000/api/update/download/latest.zip"}'
```

### 7.2 快速端到端检查（每次修改更新模块后）

```powershell
# 1. mirror 在线确认
curl http://127.0.0.1:8000/api/update/manifest
# → {"version": "...", "download_url": "...", ...}

# 2. 更新检查 API
curl http://localhost:7000/api/update/check?force=1
# → status: ok (不是 network_error 或 config_error)

# 3. Playwright UI 测试
py -m pytest application/test/portal/test_update_ui_playwright.py -v

# 4. 客户模拟测试
py application/test/portal/test_customer_full.py
```

---

## 8. 错误处理 & 恢复

### 8.1 错误状态表

| 错误 | 原因 | 用户看到 | 恢复方式 |
|------|------|---------|---------|
| `network_error` | mirror 不可达 | upgradeBtn: "无法检查更新，点击重试" | 启动 mirror / 检查网络 |
| `config_error` | 无 mirror_url 配置 | upgradeBtn: "无法检查更新，点击重试" | 检查 update_config.json |
| `incomparable` | 版本号格式异常 | upgradeBtn: "无法检查更新，点击重试" | 检查 RELEASE_INFO.json |
| `download failed` | 下载 zip 失败 | toast: "升级失败: Download failed: ..." | 检查 mirror 8000 / 重试 |
| `too small` | 下载文件 <100KB | toast: "升级失败: Downloaded file too small" | 检查 mirror 的 zip |
| `verify failed` | zip 无 RELEASE_INFO | toast: "升级失败: Not a valid release package" | 重新构建 zip |
| `PermissionError` | zip 文件锁定 | 日志警告，自动跳过 | 重试 |
| `UnicodeEncodeError` | 中文 URL 未编码 | 500 错误 | 已修复（quote 编码） |
| `workspace conflict` | zip 含用户数据文件 | 返回 `workspace_warning` 提示 | 自动备份恢复 |

### 8.2 升级失败的恢复

1. **升级脚本失败** → update.bat 记录 `ERR=1`，尝试继续后续步骤
2. **备份完好** → 用户数据在 `__ws_backup__/`，可手动恢复
3. **旧版本文件** → robocopy 不会删除旧文件（除非 zip 中同名覆盖），可手动回滚
4. **Portal 无法启动** → 用户可联系支持获取新 zip，手动解压覆盖

---

## 9. 发版 Checklist

### 9.1 发版前

- [ ] 在 `release` 分支上
- [ ] `git status` 干净（无未提交修改）
- [ ] `py -m pytest application/test/ -v` 全部 PASS
- [ ] `py application/test/portal/test_customer_full.py` PASS
- [ ] `dist/` 有旧版 zip 供客户模拟测试
- [ ] mirror 服务器可启动（`py tools/serve_mirror.py --port 8000`）
- [ ] `RELEASE_INFO.json` 版本号已更新（仓库根文件）
- [ ] `application/portal/update_config.json` mirror_urls 正确配置

### 9.2 发版中

- [ ] 执行 `py tools/release.py <version> --mirror-url http://192.168.72.219:8000/api/update/manifest --mirror-url http://192.168.5.10:8000/api/update/manifest`
- [ ] 确认构建无错误（无 0 字节 zip、无 port 替换误伤）
- [ ] 确认 git commit + push 成功

### 9.3 发版后

- [ ] `py tools/_verify_zip.py dist/帮你节省5分钟-<version>.zip <version>` 25 项全部 PASS
- [ ] 解压 zip → chcp 65001 正确、chcp 67001 不存在、端口全部 700x
- [ ] 解压包内 `update_config.json` 的 mirror_urls 不为空
- [ ] mirror 服务更新：复制新 zip 到 mirror 机器的 `dist/` → 重启 mirror
- [ ] 从客户视角验证：解压旧版 → 启动(7000) → 检查更新 → 确认 `has_update:true`
- [ ] Playwright 验证横幅和升级按钮

---

## 10. 历史错误 & 防范

> 以下从 `log/mistake.txt` 提取更新模块相关错误，已全部在代码和流程中修正。

| # | 错误 | 防范措施 |
|---|------|---------|
| 16 | manifest 无 download_url → 客户点不动升级 | 升级链路 4 步必须走通 |
| 17 | build_release 重复打包 runtime/ | EXCLUDE_DIR_NAMES 含 `runtime` |
| 18 | 过早宣称 mirror 生效，本机端到端没跑 | 必须 `curl /api/update/check?force=1` 拿到 `status:ok` |
| 19 | 开发机显示老版本号 | 发版必同步三件：zip内RELEASE_INFO + 仓库根RELEASE_INFO + update_config.json |
| 26 | 客户与 mirror 共享 7000 端口 | mirror 独立 8000 端口；客户不是 mirror |
| 36 | bat 编码 + mirror 未开 | bat 纯 ASCII；测试前确认 mirror 启动 |
| 37 | 仅测 API 没测真客户端 | 更新测试必须在解压包上运行 |
| 38 | Release 侧栏用了下载卡片 | `{% if is_release %}` 控制 dlCard ↔ upgradeBtn |
| 42 | 构建忘记 --mirror-url | memory 固化 mirror URLs |
| 43 | Mirror 未启动 | 每次测试前启动 mirror |
| 47 | URL 编码问题 | upgrade.py 用 `urllib.parse.quote()` 编码 |
| 48 | PermissionError 残留 zip | `unlink()` 增加 PermissionError 处理 |

### 更新模块修改禁忌

1. **绝不** 在 build_release EXCLUDE 列表中添加与运行时功能相关的文件
2. **绝不** 假设 mirror 是可用的 — 所有网络请求必须有超时 + try/catch
3. **绝不** 让客户 portal 同时充当 mirror
4. **绝不** 在 upgrade.py 中硬编码 BUNDLE_NAME — 使用运行时项目路径
5. **绝不** 在更新流程中猜测版本号 — 只从 RELEASE_INFO.json 读取
6. **绝不** 跳过 zip 验证直接执行升级
