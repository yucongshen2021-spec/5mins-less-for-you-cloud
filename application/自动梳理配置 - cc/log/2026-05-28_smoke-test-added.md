# 2026-05-28 新增烟雾测试

测试位置：`application/test/config_analyzer/test_smoke.py`

## 覆盖
1. `py -3 -m http.server 5742` 能启动
2. `GET /er_config_analyzer.html` 返回 200
3. 页面里包含核心 textarea `id="configText"` 和 `parseERConfig` 函数

只是入口级验证，前端 JS 的拓扑分析逻辑（`er_config_analyzer.html` 1000 多行内联 JS）依旧需要手动开页面回归。
