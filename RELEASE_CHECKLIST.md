# 发版检查清单

## 前置

- [ ] 所有代码改动已 commit 并 push
- [ ] `git status` 干净（没有未提交的修改）

## 1. 测试

```bash
# 全量测试，必须 100% 通过
py -3 -m pytest application/test/all_in_one/ -q
```

- [ ] **124 条测试全部通过**

## 2. 版本号

- [ ] `RELEASE_INFO.json` 版本号已更新
- [ ] `application/portal/update_config.json` 版本号一致

## 3. 构建前检查

- [ ] 没有 `.png` `.jpg` `.docx` 等垃圾文件残留在 `application/` 下
- [ ] `application/` 下没有测试数据目录（`screenshots/` `raw/` `user_activity/`）
- [ ] `tools/build_release.py` 排除规则包含：`*.png` `*.jpg` `*.docx` `record.json` `record.txt` `RELEASE_INFO.json`
- [ ] `tools/build_release.py` 目录排除包含：`screenshots` `raw` `user_activity`
- [ ] `start_all.bat` kill_port 端口与 `process_manager.py` 端口一致（当前：5000-5004）

## 4. 构建

```bash
# 必须带 --mirror-url，否则客户包内 mirror_url 为空，无法接收更新
py -3 tools/build_release.py --version v<版本号> --mirror-url http://<mirror服务器IP>:8000/api/update/manifest
```

- [ ] 构建成功，输出 `dist/帮你节省5分钟-<版本号>.zip`
- [ ] 无 `Duplicate name` 警告（如果有，说明 RELEASE_INFO.json 没有被排除）
- [ ] 源码文件数 ≈ 109（不应超过 120）

## 5. 构建产物验证

```bash
# 列出 zip 内容，逐项检查
py -3 -c "
import zipfile
with zipfile.ZipFile('dist/帮你节省5分钟-<版本号>.zip') as zf:
    names = zf.namelist()
    # 不应出现的文件
    for bad in ('.png', '.jpg', '.docx', 'record.json', 'record.txt', 'screenshots', '__pycache__'):
        found = [n for n in names if bad in n.lower()]
        if found:
            print(f'  GARBAGE: {bad} -> {found[:3]}')
    print(f'Total files: {len(names)}')
"
```

- [ ] zip 内无 `.png` `.jpg` `.docx` 等垃圾文件
- [ ] zip 内无 `record.json` `record.txt`
- [ ] zip 内无 `screenshots/` `raw/` `user_activity/` 目录
- [ ] `start_all.bat` 端口显示正确
- [ ] `application/portal/update_config.json` 内 `mirror_url` 已写入
- [ ] `RELEASE_INFO.json` 版本号正确

## 6. 功能冒烟（解压 zip 后手动验证）

### 6.1 启动
```bash
# 解压到一个干净目录
# 双击 start_all.bat
```

- [ ] Portal 正常启动（4/4 online）
- [ ] 点击「配置梳理」→ 页面正常加载，无 JS 报错
- [ ] 粘贴测试配置 → 点击「解析并梳理」→ 正常解析出结果
- [ ] 点击「配置生成」→ 正常加载，场景选择可用
- [ ] 点击「测试报告」→ 正常加载
- [ ] 点击「域名抓取」→ 正常加载

### 6.2 IPSec 模板
- [ ] 切换到「我来定模板」→ cascade 菜单正常显示
- [ ] 选择「Epoch FastIP → 5.0 → 非香港 · IPSec」→ 模板正常加载
- [ ] 粘贴 IPSec 数据头 → 点击「预览模板」→ 正常生成预览
- [ ] 生成配置 → 确认 NAT/GRE 路由 next-hop 为 UPE 对端 IP
- [ ] 确认 track 路由存在：`failover2 route 192.168.55.250` 和 `192.168.237.28`

### 6.3 更新检查
- [ ] Portal 首页显示正确版本号
- [ ] mirror 服务器可访问时，能检测到新版本

## 7. 发布

- [ ] 将 zip 上传到 mirror 服务器 `dist/` 目录
- [ ] 更新 mirror 服务器的 manifest（如果有的话）
- [ ] 通知用户更新

## 常见错误（不要犯）

1. **忘记 `--mirror-url`** → 客户包内 mirror_url 为空，无法检查更新
2. **构建前没清理垃圾文件** → PNG/截图被打进 zip
3. **改完代码没删 `__pycache__`** → 测试跑的是旧代码
4. **只改一处端口没同步** → start_all.bat 端口和 process_manager 不一致
5. **proxy.py 有两份代码** → 必须两份都改（第二份覆盖第一份）
6. **改了模板没清 editor_workspace** → 模板编辑器加载的是磁盘缓存，不是新代码
7. **`DEFAULT_INNER_NETS` 改了但正式页面没同步** → 需要检查 formatter 和 init defaults 两处
