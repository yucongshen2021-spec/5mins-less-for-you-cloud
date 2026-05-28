# FASTIP 自动测试报告

## 输出目录规则

- 不使用 `runs` / `release`
- 所有报告与中间文件统一在 `log/` 下
- 单次任务目录：`log/<日期YYYYMMDD>_<CID>/`

## 命令规则

- CE: `sudo -S ping -c 500 -i 0.01 -s 64|1500 <IP>`
- PC ping: `ping -n 100 -l 1200 <site>`
- PC tracert: `tracert -w 1 -d <site>`
- 默认站点：`www.baidu.com`、`www.google.com`

## GUI

```powershell
py report_gui.py
```

- Tab1: `ER FASTIP` 可输入参数并执行
- Tab2: `USG FASTIP` 开发中占位

## CLI

```powershell
py make_report.py
```

或基于已有任务目录：

```powershell
py make_report.py --resume log\<日期>_<CID>
```

## 打包

```powershell
py builder.py --build-builder
```

生成到项目根目录：
- `make_report.exe`
- `report_gui.exe`
- `builder.exe`（可选）

不会创建 `release` 文件夹。
