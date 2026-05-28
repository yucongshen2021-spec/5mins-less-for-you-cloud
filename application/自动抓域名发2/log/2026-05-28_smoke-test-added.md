# 2026-05-28 新增烟雾测试

测试位置：`application/test/domain_capture/test_smoke.py`

## 覆盖
1. `python app.py` 能启动 5739 端口
2. `GET /` 返回 200，正文非空

应用本体（包括 chromium 子目录、Playwright 爬虫逻辑）未做任何改动。
