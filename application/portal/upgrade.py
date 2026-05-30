"""在线升级：下载新版本 zip → 生成升级脚本 → 启动脚本 → portal 退出。

升级脚本（update.bat）负责：
  1. 等 portal 进程退出
  2. 强杀残留端口（5000/5739-5742）
  3. 解压新 zip 覆盖旧文件
  4. 重启 portal

用户自定义数据（editor_workspace/、.update_cache.json 等）不在发行 zip 内，
解压覆盖不会丢失。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BUNDLE_NAME = "帮你节省5分钟"

UPDATE_BAT_TEMPLATE = r"""@echo off
setlocal

echo ============================================
echo   帮你节省5分钟 - 在线升级
echo ============================================
echo.

:: 等 portal 彻底退出（最多等 15 秒）
echo [1/4] 等待 portal 退出...
set /a waited=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a waited+=1
for %%p in (5000 5739 5740 5741 5742) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        if %waited% lss 15 goto :wait_loop
    )
)

:: 强制清理残留端口
echo [2/4] 清理残留进程...
for %%p in (5000 5739 5740 5741 5742) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)

:: 解压新版本（zip 内含"帮你节省5分钟/"顶层目录，解压到 %~dp0 即覆盖当前安装）
echo [3/4] 安装新版本...
powershell -NoProfile -Command "Expand-Archive -Path '%~dp0__update__.zip' -DestinationPath '%~dp0' -Force" 2>&1
if %errorlevel% neq 0 (
    echo 解压失败！请手动解压 %~dp0__update__.zip 覆盖到当前目录。
    pause
    exit /b 1
)

:: 删除下载的 zip
del "%~dp0__update__.zip" 2>nul

:: 重启 portal
echo [4/4] 启动新版本...
echo.
start "" "%~dp0{bundle}\start_all.bat"

endlocal
exit
"""


def _download_with_progress(url: str, dest: Path, timeout: int = 120) -> None:
    """下载文件到 dest，期间每 2 秒 yield 一次已下载字节数。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "5mins-portal-upgrade",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", "0"))
        downloaded = 0
        chunk_size = 256 * 1024  # 256 KB
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                yield downloaded, total


def _verify_zip(zip_path: Path) -> dict | None:
    """验证 zip 是否包含 RELEASE_INFO.json，返回其内容或 None。"""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                if name.endswith("/RELEASE_INFO.json") or name == "RELEASE_INFO.json":
                    with zf.open(name) as f:
                        return json.loads(f.read().decode("utf-8"))
    except (zipfile.BadZipFile, OSError, json.JSONDecodeError):
        return None
    return None


def perform_upgrade(download_url: str) -> dict:
    """执行在线升级。

    1. 下载最新 zip 到项目父目录
    2. 验证 zip 合法性
    3. 生成 update.bat
    4. 启动 update.bat（新控制台窗口）
    5. 返回成功 → 前端调用 /api/shutdown 退出
    """
    parent = _PROJECT_ROOT.parent
    zip_dest = parent / "__update__.zip"
    bat_dest = parent / "__update__.bat"

    # 清理上次失败的残留
    for p in (zip_dest, bat_dest):
        p.unlink(missing_ok=True)

    # 下载
    errors: list[str] = []
    last_downloaded = 0
    try:
        for downloaded, total in _download_with_progress(download_url, zip_dest):
            last_downloaded = downloaded
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        zip_dest.unlink(missing_ok=True)
        return {
            "ok": False,
            "error": f"下载失败: {type(e).__name__}: {e}",
            "stage": "download",
        }

    if last_downloaded < 100_000:
        zip_dest.unlink(missing_ok=True)
        return {
            "ok": False,
            "error": f"下载文件异常小 ({last_downloaded} bytes)，可能不是合法 zip",
            "stage": "download",
        }

    # 验证
    release_info = _verify_zip(zip_dest)
    if release_info is None:
        zip_dest.unlink(missing_ok=True)
        return {
            "ok": False,
            "error": "下载的文件不是合法发布包（缺少 RELEASE_INFO.json）",
            "stage": "verify",
        }

    new_version = release_info.get("version", "未知")

    # 生成升级脚本
    bat_content = UPDATE_BAT_TEMPLATE.replace("{bundle}", _BUNDLE_NAME)
    bat_dest.write_text(bat_content, encoding="gbk")

    # 启动升级脚本（新控制台窗口，独立于当前进程）
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", f"帮你节省5分钟 在线升级", str(bat_dest)],
            cwd=str(parent),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as e:
        return {
            "ok": False,
            "error": f"无法启动升级脚本: {e}",
            "stage": "launch",
        }

    return {
        "ok": True,
        "new_version": new_version,
        "stage": "launched",
    }
