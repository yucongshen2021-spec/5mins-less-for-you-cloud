"""在线升级：下载新版本 zip → 生成升级脚本 → 启动脚本 → portal 退出。

升级脚本（update.bat）负责：
  1. 备份用户配置文件
  2. 等待 portal 退出 + 清理残留端口
  3. 解压新 zip → 复制到项目目录（兼容 zip 内任意文件夹名）
  4. 恢复用户配置 + 清理 __pycache__
  5. 重启 portal

关键设计：
- 不再硬编码 BUNDLE_NAME，使用运行时的实际项目路径
- 解压到临时目录再复制，不受 zip 内文件夹名影响
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_DIR = str(_PROJECT_ROOT.resolve())

_PRESERVE_FILES = [
    r"application\portal\update_config.json",
]

UPDATE_BAT_TEMPLATE = r"""@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   5mins-tools - Online Upgrade
echo   Data will be preserved. Do NOT close.
echo ============================================
echo.

set "BUNDLE={bundle_path}"
set "BACKUP=%~dp0__update_backup__"

:: ---- [1/5] Back up user config ----
echo [1/5] Backing up user config...
if exist "%BACKUP%" rmdir /s /q "%BACKUP%"
mkdir "%BACKUP%" 2>nul
if not exist "%BACKUP%" (
    echo   ERROR: cannot create backup dir
    pause
    exit /b 1
)

if exist "%BUNDLE%\application\portal\update_config.json" (
    copy /Y "%BUNDLE%\application\portal\update_config.json" "%BACKUP%\" >nul 2>&1
    if exist "%BACKUP%\update_config.json" (
        echo   Config backed up
    ) else (
        echo   WARNING: backup failed, continuing
    )
)

:: ---- [2/5] Wait for portal exit + kill ports ----
echo [2/5] Waiting for portal to exit...
set /a waited=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a waited+=1
for %%p in (7000 7001 7002 7003 7004 5000 5001 5002 5003 5004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        if !waited! lss 15 goto :wait_loop
    )
)

echo   Killing leftover processes...
for %%p in (7000 7001 7002 7003 7004 5000 5001 5002 5003 5004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
timeout /t 2 /nobreak >nul

:: ---- [3/5] Extract new version ----
echo [3/5] Installing new version...
set "TMPDIR=%~dp0__update_tmp__"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%"
powershell -NoProfile -Command "try { Expand-Archive -Path '%~dp0__update__.zip' -DestinationPath '%TMPDIR%' -Force -ErrorAction Stop } catch { exit 1 }" 2>&1
if %errorlevel% neq 0 (
    echo   ERROR: extraction failed
    echo   Try manually extracting %~dp0__update__.zip
    echo   Your config is backed up at %BACKUP%
    pause
    exit /b 1
)

:: Copy contents of the single top-level folder into BUNDLE (handles any folder name)
for /d %%d in ("%TMPDIR%\*") do (
    echo   Copying files to project...
    robocopy "%%d" "%BUNDLE%" /E /NFL /NDL /NJH /NJS /NC /NS /NP >nul 2>&1
    if %errorlevel% geq 8 (
        echo   ERROR: copy failed (code %errorlevel%)
        rmdir /s /q "%TMPDIR%" 2>nul
        pause
        exit /b 1
    )
)
rmdir /s /q "%TMPDIR%" 2>nul
del "%~dp0__update__.zip" 2>nul

:: ---- [4/5] Restore config + clean cache ----
echo [4/5] Restoring user config...

if exist "%BACKUP%\update_config.json" (
    copy /Y "%BACKUP%\update_config.json" "%BUNDLE%\application\portal\" >nul 2>&1
    if exist "%BUNDLE%\application\portal\update_config.json" (
        echo   Config restored
    ) else (
        echo   WARNING: config restore failed
    )
)

rmdir /s /q "%BACKUP%" 2>nul

echo   Cleaning Python cache...
powershell -NoProfile -Command "Get-ChildItem -Path '%BUNDLE%' -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue" 2>&1
echo   Done

:: ---- [5/5] Restart portal ----
echo [5/5] Starting new version...
echo.
start "" "%BUNDLE%\start_all.bat"

endlocal
exit
"""


def _download_with_progress(url: str, dest: Path, timeout: int = 120):
    """下载文件到 dest，期间 yield (downloaded_bytes, total_bytes)。"""
    # URL-encode non-ASCII path segments (urllib rejects raw Chinese in URLs)
    import urllib.parse
    scheme, rest = url.split("://", 1)
    if "/" in rest:
        host, path = rest.split("/", 1)
        encoded_path = "/".join(
            urllib.parse.quote(part, safe="") for part in path.split("/")
        )
        url = f"{scheme}://{host}/{encoded_path}"

    req = urllib.request.Request(url, headers={
        "User-Agent": "5mins-portal-upgrade",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", "0"))
        downloaded = 0
        chunk_size = 256 * 1024
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                yield downloaded, total


def _verify_zip(zip_path: Path) -> dict | None:
    """验证 zip 内包含 RELEASE_INFO.json，返回内容或 None。"""
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
    3. 生成 update.bat（使用实际项目路径，不硬编码目录名）
    4. 启动 update.bat → portal 退出
    """
    parent = _PROJECT_ROOT.parent
    zip_dest = parent / "__update__.zip"
    bat_dest = parent / "__update__.bat"

    # 清理上次失败的残留
    for p in (zip_dest, bat_dest):
        p.unlink(missing_ok=True)

    # 下载
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

    # 生成升级脚本 — 使用实际项目路径
    bat_content = UPDATE_BAT_TEMPLATE.replace("{bundle_path}", _PROJECT_DIR)
    bat_dest.write_text(bat_content, encoding="utf-8")

    # 启动升级脚本（新控制台窗口）
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "5mins-tools Online Upgrade", str(bat_dest)],
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
