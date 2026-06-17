#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gunicorn WSGI 入口 —— 多 worker 并发部署。

每个 worker fork 后由 gunicorn_conf.post_fork 调用 init_worker()，
各自独立加载业务模块（独立 Tk 实例 + 独立 _EMBEDDED_NS），worker 间天然并发。
不能用 gunicorn --preload：Tk/Tcl 状态不能跨 fork 继承。

裸机开发仍用 `python app.py 5003`（单进程，__main__ 自行初始化）。
"""

from app import app, init_worker, check_and_reload_runtime  # noqa: F401

# gunicorn 默认查找模块级 `application` 变量
application = app
