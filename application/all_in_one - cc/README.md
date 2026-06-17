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
| **我来定模板** | 22 场景可视化模板编辑 |

## 操作

1. 选页签 → 选变体 → 粘贴数据头 → 调参数 → 点「生成配置」
2. `Ctrl+Enter` 快捷生成
3. 模板编辑器：选场景 → 编辑 → 预览 → 保存并应用

## 数据

- 用户模板：`data/editor_workspace/`
- 出厂模板：`data/editor_defaults/`

## 测试

```bash
python test/run_all.py
```
