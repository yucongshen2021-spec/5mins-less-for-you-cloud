"""4 个非 all_in_one 应用共用的烟雾测试 helper。

提供：
  - APPLICATION_DIR：定位 application/ 根
  - launch(): subprocess.Popen 启动一个子应用入口
  - wait_port(): 等端口可连
  - http_get(): urllib 取一次首页
  - SmokeServer 上下文管理器：自动 launch+terminate
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

# application/test/_smoke_helpers.py
#   parents[0] = application/test
#   parents[1] = application
APPLICATION_DIR = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def _port_in_use(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def wait_port(port: int, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if _port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "smoke/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


@contextmanager
def SmokeServer(args: list[str], cwd: Path, port: int, extra_env: dict | None = None):
    """启动子进程，等端口起来，yield 后无论是否抛错都强制 terminate。"""
    if _port_in_use(port):
        raise RuntimeError(f"端口 {port} 已被占用，无法独立验证应用")
    env = {**os.environ, "TEST_MODE": "1", "NO_BROWSER": "1"}
    if extra_env:
        env.update(extra_env)
    proc = subprocess.Popen(
        args,
        cwd=str(cwd),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    try:
        if not wait_port(port, timeout=60.0):
            raise RuntimeError(f"等端口 {port} 超时，应用未起来")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
