# Agent 工作守则（先读，再动手）

## 第一步：先读 `log/mistake.txt`

**任何**任务开始前，先读完仓库根的 `log/mistake.txt`。
该文件只在本机维护，不进 git（`.gitignore` 已忽略），所以每台开发机看到的版本可能不同——以**本机当前版本**为准。

读完才允许动代码。

## 不可逾越的硬规则

1. **绝不兜底，绝不猜测**。失败必须显式返回 `config_error / network_error / incomparable`，前端文案禁止在异常时显示"已是最新"。任何"如果用户没传 X 就当成 Y"都要先问用户。
2. **没证据不宣称完成**。改 update / manifest / build 链路至少要拿到 `/api/update/check?force=1` 的 `status: ok` 输出 + zip duplicate 0 校验，才能说"修好了"。
3. **新犯的错立刻补进 `log/mistake.txt`**，按已有格式（现象 / 根因 / 避免）追加。不允许只在聊天里说"下次注意"。

## 高频踩坑速查（详细版本在 log/mistake.txt）

- 端口：demo `5000-5004`，release `7000-7004`。改一处必全仓库 `rg`。
- mirror_urls 顺序就是优先级：`72.219`（NAT 外层）→ `5.10`（实际服务）。
- 发新版必同步三件：构建产物 + 仓库根 `RELEASE_INFO.json` + `application/portal/update_config.json`。
- PowerShell 写 commit message：`Out-File -Encoding utf8` + `git commit -F`，禁止 `$(cat <<'EOF')`，写完 `Format-Hex` 看头三字节确认无 BOM。
- 验证 portal 模板内容用 `app.app.test_client()`，别真打 `Invoke-WebRequest /`（会被 sub-app 健康检查拖死）。
- 文件下载断言走 RFC 5987：`f"filename*=UTF-8''{quote(name)}" in disposition`。

## 跑测试的标准命令

```powershell
cd application/portal
py -3 -m pytest test_update_check.py test_update_manifest.py -q

cd ../..
py -3 -m pytest tools/test_build_release.py -q

cd application/test
py -3 -m pytest --deselect all_in_one/test_e2e_playwright.py -q
```
