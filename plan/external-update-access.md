# External Update Access Implementation Plan

**Goal:** 客户包内预置正确的 mirror_url（外部 IP），使外部客户能通过 NAT IP 拉取更新。

**Architecture:** portal 已通过 `request.host_url` 动态生成 download URL，无需修改。唯一缺口在 `build_release.py` 打包阶段——客户包的 `update_config.json` 里 mirror_url 仍是开发机 LAN IP。

---

### Task 1: build_release.py 新增 --mirror-url 参数

- [ ] 新增 CLI 参数 `--mirror-url`
- [ ] 在 zip 写入循环中，匹配 `update_config.json` 时注入指定的 mirror_url
- [ ] 未指定时打印提醒（建议配置 mirror_url）

### Task 2: 构建测试

- [ ] 用 `--mirror-url http://192.168.72.219:5000/api/update/manifest` 打包
- [ ] 验证 zip 内 update_config.json 的 mirror_url 正确
- [ ] 跑 simulate_customer.py 验证端到端

### Task 3: 记录日志

- [ ] 写 log/2026-05-30.md 追加修改记录
