"""domain_capture 测试 —— 依赖 playwright + 本地 Chromium（当前镜像未安装）。

缺失时整组自动跳过：CI / 无浏览器环境不阻塞 workflow；本地装了 playwright 时正常执行。
（用 fixture 形式而非 conftest 级 importorskip：后者会让 pytest 在收集阶段直接报错。）
"""
import pytest


@pytest.fixture(scope="session", autouse=True)
def _require_playwright():
    pytest.importorskip("playwright", reason="需要 playwright + Chromium（未安装环境自动跳过）",
                        exc_type=ImportError)
