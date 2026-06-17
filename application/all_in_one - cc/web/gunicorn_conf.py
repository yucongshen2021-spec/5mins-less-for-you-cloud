#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gunicorn 配置 —— all_in_one 多 worker 并发。

关键约束：
- preload_app = False：Tk/Tcl 状态不能跨 fork 继承，必须每 worker 各自初始化。
- 每个 worker 内仍单线程（业务模块用 tkinter exec，非线程安全）；
  并发靠 worker 间进程隔离实现。
- --max-requests 防止 tkinter/模块内存长期累积泄漏。
"""

import os

# 监听地址（supervisord 里也会指定 -b，这里作默认）
bind = ["127.0.0.1:5003"]

# worker 数：默认 8（4c4g 可支持）。可用 GUNICORN_WORKERS 环境变量覆盖。
workers = int(os.environ.get("GUNICORN_WORKERS", "8"))

# worker 类型：默认 sync（每 worker 单线程串行处理），符合 tkinter 单线程约束。
worker_class = "sync"

# 单请求超时（秒）。配置生成不应这么久，保护性设置。
timeout = 120

# 优雅退出宽限：给 worker 完成在途请求的时间。
graceful_timeout = 30

# worker 处理 max_requests 个请求后重启，防内存/tkinter 状态累积。
max_requests = 200
max_requests_jitter = 20

# 不预加载应用（Tk 不能跨 fork）。
preload_app = False

# 关闭 accesslog 噪音（portal 层已记访问日志到 stats_db）。
accesslog = None
errorlog = "-"


def post_fork(server, worker):
    """每个 worker 启动后初始化业务模块。"""
    try:
        import wsgi
        wsgi.init_worker()
        worker.log.info("worker init done: modules preloaded")
    except Exception as e:
        worker.log.error(f"worker init FAILED: {e}", exc_info=True)
        raise


def on_worker_exit(server, worker):
    """worker 退出时清理（如有需要）。"""
    pass
