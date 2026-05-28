# 2026-05-28 新增 portal 烟雾测试

测试位置：`application/test/portal/test_smoke.py`

## 覆盖
1. `python app.py` 能启动 5000 端口
2. `GET /` 返回 200，正文非空
3. `GET /api/status` 返回 list，且 id 集合至少包含
   `{all_in_one, test_report, domain_capture, config_analyzer}`

## 已知限制
portal 启动时会拉起 4 个子应用，但 fixture 退出时 `terminate` portal 父进程在 Windows 上不会触发 `atexit`，所以子进程要靠 `psutil` 显式杀掉。

依赖：`psutil`。
