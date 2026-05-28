# ER/USG 配置梳理 GUI

`er_config_analyzer_gui.py` 是一个本地 Python GUI 工具，支持 `ER` 与 `USG` 两个场景，通过 Tab 切换后分别解析出口关系。

## 功能

- 通过 Tab 切换 `ER` / `USG` 场景
- 读取/粘贴 ER 或 USG 全量配置脚本
- 读取/粘贴假 IP 与真 IP 对应关系
- 自动梳理并输出：
  - 内网 IP / 网段
  - NAT 规则号
  - 出口接口（规则维度）
  - 出口归并名称
  - 假 IP、真 IP、映射状态
- 支持导出 CSV

## 真假 IP 输入格式

支持多种写法混合输入（1 对 1）：

- `10.60.44.28-218.32.88.83；10.60.18.22-150.116.112.236`
- `10.60.44.28=218.32.88.83`
- `10.60.44.28:218.32.88.83`
- `10.60.44.28 -> 218.32.88.83`

可使用中文/英文分号、换行分隔多条映射。

## 运行方式

在 PowerShell 中执行：

```powershell
py "C:\Users\123\Desktop\自动梳理配置\er_config_analyzer_gui.py"
```

## 使用步骤

1. 在顶部 Tab 选择场景（`ER` 或 `USG`）。
2. 点击“导入配置文件”或直接粘贴对应场景配置到左侧输入框。
3. 在右侧输入框粘贴假 IP-真 IP 对应关系。
4. 点击“解析并梳理”查看结果。
5. 点击“导出CSV”保存结果。

## 说明

- 程序会优先使用 NAT 规则中的 `source address` 作为内网 IP/网段；若缺失则回退到 `destination address`。
- 默认 WAN `masquerade` 规则会被自动忽略，聚焦海外出口映射规则。
- USG 场景会解析 `ip address-set` 与 `nat-policy`，聚焦 `source-nat address-group` 类型的海外出口 SNAT 规则。
- 如果某个假 IP 未在映射输入中提供，真 IP 显示为“(未提供)”。
