# 2026-05-28 测试迁出 + webbrowser 守卫

## 测试目录搬走
`application/all_in_one - cc/test/` 已整体移到 `application/test/all_in_one/`。该 app 自身现在只剩 `src/ web/ log/ build_exe.spec`。

迁出 17 个 .py（含 `test_er5/` 2 个）。空目录已清理。

## web/app.py 改动
`__main__` 入口的自动开浏览器逻辑加了一层守卫：

```python
if os.environ.get("TEST_MODE") != "1" and os.environ.get("NO_BROWSER") != "1":
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
```

原因：Playwright E2E / 自动化场景下 `webbrowser.open` 会去启动用户默认浏览器，无意义且偶发挂起。正常用户启动（`start_all.bat`）不带 `TEST_MODE`，行为不变。

## 验证
- 全量 Python 测试（39 用例）：通过
- Playwright E2E `--quick`（42 用例）：通过
