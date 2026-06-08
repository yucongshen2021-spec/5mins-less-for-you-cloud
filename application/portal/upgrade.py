"""在线升级：下载新版本 zip → 生成升级脚本 → 启动脚本 → portal 退出。

升级脚本（update.bat）负责：
  1. 等 portal 进程退出
  2. 强杀残留端口
  3. 备份用户 workspace → 4. 解压新 zip → 5. 恢复 workspace
  6. 重启 portal

关键设计：
- 不再硬编码 BUNDLE_NAME，使用运行时的实际项目路径
- 解压到临时目录再复制，不受 zip 内文件夹名影响
- bat 纯 ASCII 输出（无编码依赖）
- 零 pause 语句 — 完全自动化，错误仅记录不阻塞
"""
from __future__ import annotations

import json
import subprocess
import urllib.request
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROJECT_DIR = str(_PROJECT_ROOT.resolve())

_PROTECTED_PATHS = [
    "application/all_in_one - cc/data/editor_workspace",
    "user_init_placeholders.json",
    ".update_cache.json",
]

UPDATE_BAT_TEMPLATE = r"""@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   5mins-tools release - Online Upgrade
echo ============================================
echo.

set "BUNDLE={bundle_path}"
set "ERR=0"

:: ---- [1/6] Wait for portal to exit ----
echo [1/6] Waiting for portal to exit...
set /a waited=0
:wait_loop
timeout /t 1 /nobreak >nul
set /a waited+=1
set "any=0"
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do set "any=1"
)
if !any!==1 if %waited% lss 20 goto :wait_loop

:: ---- [2/6] Kill leftover ports ----
echo [2/6] Killing leftover processes...
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
timeout /t 3 /nobreak >nul

:: ---- [3/6] Backup user workspace ----
echo [3/6] Protecting user data...
set "BAK=%~dp0__ws_backup__"
if exist "%BAK%" rd /s /q "%BAK%" 2>nul
mkdir "%BAK%" 2>nul
call :backup "%BUNDLE%\application\all_in_one - cc\data\editor_workspace" "editor_workspace"
call :backup_file "%BUNDLE%\user_init_placeholders.json"
call :backup_file "%BUNDLE%\.update_cache.json"

:: ---- [4/6] Extract + copy new version ----
echo [4/6] Installing new version...
set "TMPDIR=%~dp0__update_tmp__"
if exist "%TMPDIR%" rmdir /s /q "%TMPDIR%" 2>nul

powershell -NoProfile -Command "try { Expand-Archive -Path '%~dp0__update__.zip' -DestinationPath '%TMPDIR%' -Force -ErrorAction Stop } catch { exit 1 }" 2>&1
if %errorlevel% neq 0 (
    echo   Retrying extraction...
    timeout /t 2 /nobreak >nul
    powershell -NoProfile -Command "try { Expand-Archive -Path '%~dp0__update__.zip' -DestinationPath '%TMPDIR%' -Force -ErrorAction Stop } catch { exit 1 }" 2>&1
    if %errorlevel% neq 0 set "ERR=1"
)

if not "%ERR%"=="1" (
    for /d %%d in ("%TMPDIR%\*") do (
        echo   Copying files - this may take a moment
        robocopy "%%d" "%BUNDLE%" /E /R:3 /W:3 /NFL /NDL /NJH /NJS /NC /NS /NP >nul 2>&1
        if %errorlevel% geq 8 (
            echo   WARNING: some files could not be copied - code %errorlevel%
            set "ERR=1"
        )
    )
)

rmdir /s /q "%TMPDIR%" 2>nul
del "%~dp0__update__.zip" 2>nul

:: ---- [5/6] Restore user workspace ----
echo [5/6] Restoring user data...
call :restore "%BUNDLE%\application\all_in_one - cc\data\editor_workspace" "editor_workspace"
call :restore_file "%BUNDLE%\user_init_placeholders.json"
call :restore_file "%BUNDLE%\.update_cache.json"
rd /s /q "%BAK%" 2>nul

:: ---- [6/6] Restart portal ----
echo [6/6] Starting new version...
echo.
:: Endlocal discards local env; save BUNDLE path to a file first.
echo %BUNDLE%> "%TEMP%\__upgrade_bundle__.tmp"
endlocal
set /p BUNDLE=<"%TEMP%\__upgrade_bundle__.tmp"
del "%TEMP%\__upgrade_bundle__.tmp" 2>nul
set "RELEASE_MODE=1"
start "" "%BUNDLE%\start_all.bat"
exit

:: ---- Helper functions ----
:backup
if exist "%~1" (
    mkdir "%BAK%\%~2" 2>nul
    robocopy "%~1" "%BAK%\%~2" /E /R:0 /W:0 /NP /NFL /NDL /NJH /NJS >nul
)
exit /b

:backup_file
if exist "%~1" copy /Y "%~1" "%BAK%\%~2" >nul
exit /b

:restore
if exist "%BAK%\%~2" (
    if not exist "%~1" mkdir "%~1"
    robocopy "%BAK%\%~2" "%~1" /E /R:0 /W:0 /NP /NFL /NDL /NJH /NJS >nul
)
exit /b

:restore_file
if exist "%BAK%\*%~2" copy /Y "%BAK%\%~2" "%~1" >nul
exit /b
"""


def _scan_zip_for_conflicts(zip_path: Path) -> list[str]:
    conflicts: list[str] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                for protected in _PROTECTED_PATHS:
                    if name.endswith("/" + protected) or name.endswith("\\" + protected) \
                       or protected in name.split("/") or protected in name.split("\\"):
                        conflicts.append(protected)
                        break
    except (zipfile.BadZipFile, OSError):
        pass
    return list(dict.fromkeys(conflicts))


def _download_with_progress(url: str, dest: Path, timeout: int = 120):
    import urllib.parse
    scheme, rest = url.split("://", 1)
    if "/" in rest:
        host, path = rest.split("/", 1)
        encoded_path = "/".join(
            urllib.parse.quote(part, safe="") for part in path.split("/")
        )
        url = f"{scheme}://{host}/{encoded_path}"

    req = urllib.request.Request(url, headers={"User-Agent": "5mins-portal-upgrade"})
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
    parent = _PROJECT_ROOT / "temp" / "upgrade"
    parent.mkdir(parents=True, exist_ok=True)
    zip_dest = parent / "__update__.zip"
    bat_dest = parent / "update.bat"

    for p in (zip_dest, bat_dest):
        try:
            p.unlink(missing_ok=True)
        except PermissionError:
            pass

    last_downloaded = 0
    try:
        for downloaded, _total in _download_with_progress(download_url, zip_dest):
            last_downloaded = downloaded
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        zip_dest.unlink(missing_ok=True)
        return {"ok": False, "error": f"Download failed: {type(e).__name__}: {e}", "stage": "download"}

    if last_downloaded < 100_000:
        zip_dest.unlink(missing_ok=True)
        return {"ok": False, "error": f"Downloaded file too small ({last_downloaded} bytes)", "stage": "download"}

    release_info = _verify_zip(zip_dest)
    if release_info is None:
        zip_dest.unlink(missing_ok=True)
        return {"ok": False, "error": "Not a valid release package (missing RELEASE_INFO.json)", "stage": "verify"}

    conflicts = _scan_zip_for_conflicts(zip_dest)
    new_version = release_info.get("version", "unknown")

    bat_content = UPDATE_BAT_TEMPLATE.replace("{bundle_path}", _PROJECT_DIR)
    bat_dest.write_text(bat_content, encoding="utf-8")

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "5mins-tools Online Upgrade", str(bat_dest)],
            cwd=str(parent),
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as e:
        return {"ok": False, "error": f"Cannot start upgrade script: {e}", "stage": "launch"}

    result: dict = {"ok": True, "new_version": new_version, "stage": "launched"}
    if conflicts:
        result["workspace_warning"] = (
            f"New zip contains protected user data files. "
            f"Upgrade script will backup and restore: {', '.join(conflicts)}"
        )
    return result
