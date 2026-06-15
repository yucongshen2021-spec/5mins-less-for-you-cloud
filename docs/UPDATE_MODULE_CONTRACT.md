# 自动更新模块 — 固化契约（FROZEN）

> 本文件定义"在线升级"模块的**不变量**（invariants）。每一条都对应一个曾被违反、
> 已修复并锁进测试的规则。改动本模块任何文件前，先读本文件，再读
> [`log/mistake.txt`](../log/mistake.txt) #16 #26 #33 #36 #47 #54 #55 #56。

## 涉及文件

| 文件 | 角色 |
|---|---|
| `application/portal/update_check.py` | 版本检查（多源优先级 + 语义比较 + 缓存） |
| `application/portal/upgrade.py` | 下载 + 校验 + 生成 update.bat + 启动 |
| `application/portal/update_config.json` | 客户端配置（mirror_urls 优先级顺序） |
| `application/portal/app.py` | `/api/update/check` `/api/update/upgrade` `/api/shutdown` |
| `application/portal/templates/index.html` | 前端 5 态按钮 + 横幅 + 自动检查 |
| `tools/serve_mirror.py` | mirror 服务（manifest + 下载端点） |
| `tools/build_release.py` | 打包（注入 mirror_url + 端口替换） |
| `tools/_verify_zip.py` | 打包后 zip 不变量校验 |

## 不变量（每条都不可违反，违反就是 bug）

### INV-1：URL 编码契约 = RFC 合规预编码，且重编码幂等

- **serve_mirror `build_manifest`** 发出的 `download_url` **必须 percent-encode 文件名**
  （`urllib.parse.quote(filename, safe="")`）。绝不能发原始中文字面量。
- **upgrade `_encode_url_idempotent`** 必须幂等：`quote(unquote(part))`。
  原始中文 URL 和已编码 URL 输入得到同一输出，**绝不产生 `%25`**。
- 锁定测试：`application/test/portal/test_upgrade_url_encode.py`（7 + 1 + 1 = 9 用例）。
- 历史根因：mistake #47（盲目 quote 双编码）+ #54（契约不一致）。

### INV-2：升级失败绝不冒泡成未捕获 500

- `perform_upgrade` 的 except 必须覆盖
  `URLError, HTTPError, TimeoutError, OSError, ValueError`。
  `ValueError` 覆盖 `UnicodeEncodeError`（任何漏网的非 ASCII URL）。
- 返回结构：`{"ok": False, "error": "...", "stage": "download|verify|launch"}`。
- 锁定测试：`test_upgrade_url_encode.py::TestPerformUpgradeErrorHandling`。

### INV-3：版本比较严守"不猜测"

- 失败/无配置/不可比较时返回 `status: config_error | network_error`，
  `comparison: incomparable`，`has_update: False`。
- **绝不**在网络失败时假装"已是最新"。前端文案禁止异常时显示"已是最新"。
- 锁定测试：`test_update_check.py`（25 用例）。
- 历史根因：mistake #26。

### INV-4：端口运行时切换，构建时不替换 app.py/process_manager.py

- `app.py` 必须含 `_PORT = 7000 if _RELEASE else 5000`（字面）。
- `process_manager.py` 必须含 `_BASE = 7000 if _RELEASE else 5000`（字面）+ `_BASE + 1..4`。
- `build_release._RELEASE_PORT_FILES` **不得**包含这两个文件
  （它们自带运行时分支，替换会废掉 demo fallback）。
- 锁定测试：`_verify_zip.py` M#35 / M#2（runtime switch intact）。
- 历史根因：mistake #33 / #35 / #55。

### INV-5：mirror 独立进程，端口 8000

- mirror（provider）和 portal（consumer）是两个独立进程，**不共享端口**。
- 客户端 `update_config.json` 的 `mirror_urls` 指向 dev 机器的 8000 端口，
  顺序即优先级：`72.219`（主）→ `5.10`（备）。
- 测试更新功能前必须先起 mirror：`py tools/serve_mirror.py --port 8000`。
- 锁定测试：`test_upgrade_real_e2e.py` 自动起 mirror。
- 历史根因：mistake #26 / #43。

### INV-6：update.bat 纯 ASCII、零 chcp、零 pause、保护用户数据

- bat 模板（`upgrade.UPDATE_BAT_TEMPLATE`）只含英文 echo，不含中文、不含 chcp、不含 pause。
- 6 步：等退出 → 杀端口 → 备份 workspace/placeholders/cache → 解压 → robocopy → 恢复 → 重启。
- `endlocal` 必须在 `start` 之前（防环境变量泄漏）。
- 锁定测试：`test_upgrade_bat.py`（静态 + 步骤 + 真实 cmd 语法）。
- 历史根因：mistake #33 / #36 / #46。

### INV-7：真实升级链路用时 ~190s，测试窗口 ≥ 300s

- robocopy 复制 ~4000 个 runtime 文件是大头（~100-110s）。
- e2e 测试重启等待窗口必须 ≥ 300s（实测 ~189s + 余量）。
- 升级失败时测试保留 temp 目录供事后排查。
- 锁定测试：`test_upgrade_real_e2e.py`（300s 窗口）。
- 历史根因：mistake #56。

### INV-8：Playwright 真实点击是铁律，API 200 ≠ UI 可用

- 更新模块的任何改动，必须通过 `test_upgrade_real_e2e.py`（真浏览器点击 +
  真下载 + 真 bat 执行 + 真重启），不能只用 curl/pytest 就宣称通过。
- 现有 `test_customer_full.py` 用 `page.route()` 拦截 upgrade API，**不验证真升级**
  （只验证 UI 状态机）——它和 `test_upgrade_real_e2e.py` 互补，不能互相替代。
- 历史根因：mistake #37 / #52。

## 端到端验证清单（改本模块后必跑）

```powershell
# 1. 离线单元（秒级）
py -3 -m pytest application/test/portal/test_update_check.py `
                    application/test/portal/test_upgrade_url_encode.py `
                    application/test/portal/test_upgrade_bat.py -q

# 2. smoke + release（需要 7000-7004 空闲）
py -3 -m pytest application/test/portal/test_smoke.py `
                    application/test/portal/test_release.py -q

# 3. 真实升级 e2e（~4 分钟，需要 dist/ 有新旧两版 zip）
py -3 -u application/test/portal/test_upgrade_real_e2e.py

# 4. 构建后 zip 校验
py -3 tools/_verify_zip.py dist/帮你节省5分钟-<ver>.zip <ver>
```

全部绿才算改完。
