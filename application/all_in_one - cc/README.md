# all_in_one · 网络配置生成工具

## 启动

```bash
cd web && python app.py
```

浏览器打开 `http://localhost:5003`（由 portal 反向代理统一入口 `http://localhost:5000/app/all_in_one/` 暴露）。

## 最近更新告示栏

顶栏右侧 📣 按钮展开最近更新列表（日期/标题/简介）。内容来自 `data/whatsnew/updates.json`，由 `index()` 服务端渲染。未读小红点由 `localStorage('whatsnew_lastSeen')` 控制，点开即标记已读；点 ✕ 或弹层外部收起。新增功能只需编辑该 JSON。

## 页签

| 页签 | 功能 |
|------|------|
| **Epoch FastIP** | ER 4.0：HK / HK·IPSec / 非香港 / 非香港·IPSec / 单出口(无备线) / 飞连 / 新增出口 / 域名分流（8 变体）；ER 5.0 切换入口当前「测试中」 |
| **USG FastIP** | HK / 非香港 / 飞连 / 新增出口（4 变体） |
| **Epoch MPLS** | 国内 / 海外 / IPSec（3 变体） |
| **AR SD-WAN** | 单机 / 双机 · OPS + Factory（8 变体）——页签当前「测试中」禁用 |
| **AR 传统组网** | 双线 |
| **我来定模板** | 31 场景可视化模板编辑（登录用户可编辑，访客只读） |
| **感谢** | 致谢页 |

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
python -m pytest blackbox_8000/ -q                              # 86 项黑箱（含 28 项多用户并发，需 8000 容器）
# 单元/回归（从仓库根运行）：147 项，17 项浏览器用例自动跳过
cd ../.. && python -m pytest application/test/all_in_one -q
# 综合测试（容器内 in-process）：280 项
sudo docker exec fivemins-portal-test sh -c 'cd "/app/application/test/all_in_one" && python3 comprehensive.py'
```
