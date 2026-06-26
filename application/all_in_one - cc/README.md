# all_in_one · 网络配置生成工具

## 启动

```bash
cd web && python app.py
```

浏览器打开 `http://localhost:5003`（由 portal 反向代理统一入口 `http://localhost:5000/app/all_in_one/` 暴露）。

## 页签

| 页签 | 功能 |
|------|------|
| **Epoch FastIP** | HK / 非HK / 飞连 / 新增出口 / 域名分流 |
| **USG FastIP** | 非HK / HK / 飞连 / 新增出口 |
| **Epoch MPLS** | 国内 / 海外 / IPSec |
| **AR SD-WAN** | 单机 / 双机 · OPS 脚本 + Factory 配置 |
| **我来定模板** | 29 场景可视化模板编辑（登录用户可编辑，访客只读） |

## 操作

1. 选页签 → 选变体 → 粘贴数据头 → 调参数 → 点「生成配置」
2. `Ctrl+Enter` 快捷生成
3. 模板编辑器：选场景 → 编辑 → 预览 → 保存并应用

## 权限控制

- **登录用户**可以编辑自己的模板（save/reset/preview 模板 + init-defaults）
- **访客（未登录）**不可编辑，按钮置灰，显示"请登录后编辑专属脚本模板"提示横幅
- 后端 5 个 API 路由有 `_require_login()` 403 拦截（检查 `X-User-Id` 非空）
- 前端 `TEMPLATE_EDITABLE` 变量控制按钮状态，`IS_ADMIN` 标识 yucs 管理员
- 保存模板时自动在 `.tpl` 顶部加注释：`# xxx专属yyy场景模板-yymmdd`

## 数据

- 按用户隔离：`data/users/<user_id>/editor_workspace/`（每个登录用户独立）
- 出厂模板：`data/editor_defaults/`
- 访客（未登录）：使用共享 `data/` 根目录

## 测试

```bash
cd application/test
python -m pytest blackbox_8000/test_full_api.py -q          # 58 API 测试
python -m pytest all_in_one/test_apis.py test_generation.py -q  # 单元测试
```
