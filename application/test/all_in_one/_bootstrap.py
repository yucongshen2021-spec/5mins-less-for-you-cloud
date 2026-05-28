"""共享路径引导：把 all_in_one - cc 的 web/src 加入 sys.path。

所有 application/test/all_in_one/ 下的测试都 `import _bootstrap`，
不再各自计算 parent/parent。迁移到 application/test/ 后这是唯一的路径锚点。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# application/test/all_in_one/_bootstrap.py
#   parents[0] = application/test/all_in_one
#   parents[1] = application/test
#   parents[2] = application
APP_DIR = Path(__file__).resolve().parents[2] / "all_in_one - cc"
WEB_DIR = APP_DIR / "web"
SRC_DIR = APP_DIR / "src"

if not APP_DIR.is_dir():
    raise RuntimeError(f"all_in_one - cc 目录不存在: {APP_DIR}")

for p in (str(WEB_DIR), str(SRC_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# 所有测试都假定 TEST_MODE=1（关闭活动日志写入等副作用）
os.environ.setdefault("TEST_MODE", "1")

__all__ = ["APP_DIR", "WEB_DIR", "SRC_DIR"]
