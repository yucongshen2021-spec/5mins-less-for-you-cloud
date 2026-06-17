# FASTIP 自动测试报告

## 输出目录规则

- 不使用 `runs` / `release`
- 所有报告与中间文件统一在 `log/` 下
- 单次任务目录：`log/<日期YYYYMMDD>_<CID>/`

## 命令规则

- CE: `sudo -S ping -c 500 -i 0.01 -s 64|1500 <IP>`
- PC ping (Linux): `ping -c 100 -s 1200 <site>`
- PC ping (Windows): `ping -n 100 -l 1200 <site>`
- PC traceroute (Linux): `traceroute -w 1 -n <site>`
- PC tracert (Windows): `tracert -w 1 -d <site>`
- 默认站点：`www.baidu.com`、`www.google.com`

## Web 入口

```bash
python app.py
```

- Tab1: `ER FASTIP` 可输入参数并执行
- Tab2: `USG FASTIP` 开发中占位

## CLI

```bash
python src/make_report.py
```

或基于已有任务目录：

```bash
python src/make_report.py --resume log/<日期>_<CID>
```
