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
import sys
import urllib.request
import zipfile
from pathlib import Path

_IS_WIN = sys.platform == "win32"

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

:: Compute bundle path from BAT location (bat is at BUNDLE\temp\upgrade\update.bat)
for %%I in ("%~dp0..\..") do set "BUNDLE=%%~fI"
set "ERR=0"

:: ---- [1/6] Wait for portal to exit ----
echo [1/6] Waiting for portal to exit...
set /a waited=0
:wait_loop
ping 127.0.0.1 -n 2 >nul
set /a waited+=1
set "any=0"
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do set "any=1"
)
if !any!==1 if %waited% lss 30 goto :wait_loop

:: ---- [2/6] Kill leftover ports ----
echo [2/6] Killing leftover processes...
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr /c:":%%p " ^| findstr "LISTENING" 2^>nul') do (
        taskkill /F /PID %%a >nul 2>&1
    )
)
ping 127.0.0.1 -n 4 >nul

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
    ping 127.0.0.1 -n 3 >nul
    powershell -NoProfile -Command "try { Expand-Archive -Path '%~dp0__update__.zip' -DestinationPath '%TMPDIR%' -Force -ErrorAction Stop } catch { exit 1 }" 2>&1
    if %errorlevel% neq 0 set "ERR=1"
)

if not "%ERR%"=="1" (
    :: Unlock any read-only files before copy
    powershell -NoProfile -Command "Get-ChildItem '%TMPDIR%' -Recurse | ForEach-Object { try { $_.Attributes = 'Normal' } catch {} }" 2>nul
    for /d %%d in ("%TMPDIR%\*") do (
        echo   Copying files - this may take a moment
        robocopy "%%d" "%BUNDLE%" /E /R:3 /W:3 /NFL /NDL /NJH /NJS /NC /NS /NP >nul 2>&1
        if %errorlevel% geq 8 (
            echo   WARNING: some files could not be copied - code %errorlevel%
            set "ERR=1"
        )
    )
    :: Verify RELEASE_INFO.json was copied
    if not exist "%BUNDLE%\RELEASE_INFO.json" (
        echo   ERROR: RELEASE_INFO.json missing after copy
        set "ERR=1"
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


def _encode_url_idempotent(url: str) -> str:
    """Percent-encode a URL's path so it is safe for urllib, WITHOUT double-encoding.

    Why this exists (see log/mistake.txt #47 + #54):
      - urllib.request cannot put raw non-ASCII (e.g. the 中文 bundle filename) on
        the HTTP request-target → UnicodeEncodeError.
      - The original fix blindly re-quoted every path segment, which turned an
        already-percent-encoded URL (GitHub asset, RFC-compliant mirror) into a
        double-encoded one (%E5 → %25E5 → 404). That was a latent bug: it only
        "worked" because serve_mirror happened to emit raw filenames, so two bugs
        cancelled out.

    This helper is idempotent: it unquotes first, then quotes once, so calling it
    on a raw URL or an already-encoded URL yields the same correct result.
    """
    import urllib.parse
    split = urllib.parse.urlsplit(url)
    # Normalize each path segment: unquote (idempotent) then quote once.
    encoded_path = "/".join(
        urllib.parse.quote(urllib.parse.unquote(part), safe="")
        for part in split.path.split("/")
    )
    return urllib.parse.urlunsplit(
        (split.scheme, split.netloc, encoded_path, split.query, split.fragment)
    )


def _download_with_progress(url: str, dest: Path, timeout: int = 120):
    url = _encode_url_idempotent(url)

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


def _load_mirror_base_urls() -> list[str]:
    """Load mirror base URLs from update_config.json for download fallback.

    The config stores manifest URLs like:
      http://192.168.72.219:8000/api/update/manifest
    We strip the path to get the base: http://192.168.72.219:8000
    """
    import urllib.parse as _up
    urls: list[str] = []
    try:
        cfg_path = _PROJECT_ROOT / "application" / "portal" / "update_config.json"
        if cfg_path.is_file():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            for key in ("mirror_url", "mirror_urls"):
                v = cfg.get(key)
                if isinstance(v, str) and v.strip():
                    urls.append(v.strip().rstrip("/"))
                elif isinstance(v, list):
                    for u in v:
                        if isinstance(u, str) and u.strip():
                            urls.append(u.strip().rstrip("/"))
    except Exception:
        pass
    # Strip manifest path to get base URL (scheme + netloc only)
    bases: list[str] = []
    for url in list(dict.fromkeys(urls)):
        parts = _up.urlsplit(url)
        bases.append(f"{parts.scheme}://{parts.netloc}")
    return bases


def _try_download(download_url: str, zip_dest: Path) -> tuple[int, str, int, int]:
    """Try downloading from one URL. Returns (downloaded_bytes, error_msg, last_progress_pct, total_size)."""
    last = 0
    total = 0
    err = ""
    try:
        for d, t in _download_with_progress(download_url, zip_dest):
            last = d
            total = t
    except (urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, OSError, ValueError) as e:
        err = f"{type(e).__name__}: {e}"
    pct = int(last * 100 / total) if total > 0 else 0
    return last, err, pct, total


def _build_alt_download_urls(original_url: str, base_urls: list[str]) -> list[str]:
    """Build alternative download URLs by swapping the base URL.
    Example: http://10.0.0.1:8000/api/update/download/xxx.zip
             -> http://10.0.0.2:8000/api/update/download/xxx.zip
    """
    import urllib.parse as _up
    alt_urls: list[str] = []
    try:
        parts = _up.urlsplit(original_url)
        path_segments = parts.path.strip("/").split("/")
        # Find the filename (last segment) and the prefix path
        if len(path_segments) >= 2:
            filename = path_segments[-1]
            prefix = "/".join(path_segments[:-1])  # e.g. "api/update/download"
            for base in base_urls:
                alt = f"{base}/{prefix}/{filename}"
                if alt != original_url:
                    alt_urls.append(alt)
    except Exception:
        pass
    return alt_urls


def perform_upgrade_progress(download_url: str):
    """Generator version — yields progress dicts for SSE streaming."""
    parent = _PROJECT_ROOT / "temp" / "upgrade"
    parent.mkdir(parents=True, exist_ok=True)
    zip_dest = parent / "__update__.zip"
    bat_dest = parent / "update.bat"

    for p in (zip_dest, bat_dest):
        try:
            p.unlink(missing_ok=True)
        except PermissionError:
            pass

    # ── Download (with real-time progress) ──
    def _do_download(url, dest):
        """Download with real-time progress yields. Returns (bytes, error)."""
        last = 0; total = 0; err = ""
        try:
            url2 = _encode_url_idempotent(url)
            req = urllib.request.Request(url2, headers={"User-Agent": "5mins-portal-upgrade"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", "0"))
                downloaded = 0
                chunk_size = 256 * 1024
                last_pct = -1
                with open(dest, "wb") as f:
                    while True:
                        chunk = resp.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = int(downloaded * 100 / total)
                            if pct > last_pct:
                                last_pct = pct
                                yield {"stage": "download", "pct": pct,
                                       "message": f"{downloaded//1024//1024}/{total//1024//1024} MB"}
                last = downloaded
        except (urllib.error.URLError, urllib.error.HTTPError,
                TimeoutError, OSError, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
        yield ("__RESULT__", last, err)

    # Primary download
    yield {"stage": "download", "message": "正在连接...", "pct": 0}
    gen = _do_download(download_url, zip_dest)
    last_downloaded = 0; err = ""
    for update in gen:
        if isinstance(update, dict):
            yield update
        elif isinstance(update, tuple) and len(update) == 3 and update[0] == "__RESULT__":
            last_downloaded, err = update[1], update[2]

    # Retry with alternative mirrors
    if err and last_downloaded < 100_000:
        mirror_urls = _load_mirror_base_urls()
        alt_urls = _build_alt_download_urls(download_url, mirror_urls)
        for alt_url in alt_urls:
            if last_downloaded >= 100_000:
                break
            zip_dest.unlink(missing_ok=True)
            print(f"[UPGRADE] Retrying download with: {alt_url}", flush=True)
            yield {"stage": "download", "message": "切换备用线路...", "pct": 0}
            gen2 = _do_download(alt_url, zip_dest)
            for update in gen2:
                if isinstance(update, dict):
                    yield update
                elif isinstance(update, tuple) and len(update) == 3 and update[0] == "__RESULT__":
                    last_downloaded, err = update[1], update[2]

    if err and last_downloaded < 100_000:
        zip_dest.unlink(missing_ok=True)
        yield {"ok": False, "error": f"Download failed: {err}", "stage": "download"}
        return

    if last_downloaded < 100_000:
        zip_dest.unlink(missing_ok=True)
        yield {"ok": False, "error": f"Downloaded file too small ({last_downloaded} bytes)", "stage": "download"}
        return

    # ── Verify ──
    yield {"stage": "verify", "message": "正在验证更新包...", "pct": 100}
    release_info = _verify_zip(zip_dest)
    if release_info is None:
        zip_dest.unlink(missing_ok=True)
        yield {"ok": False, "error": "Not a valid release package (missing RELEASE_INFO.json)", "stage": "verify"}
        return

    conflicts = _scan_zip_for_conflicts(zip_dest)
    new_version = release_info.get("version", "unknown")

    # ── Install ──
    yield {"stage": "install", "message": "正在准备安装...", "pct": 100}
    bat_dest.write_text(UPDATE_BAT_TEMPLATE, encoding="ascii")

    try:
        if _IS_WIN:
            subprocess.Popen(
                ["cmd", "/c", "start", "5mins-tools Online Upgrade", str(bat_dest)],
                cwd=str(parent),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        else:
            yield {"ok": False, "error": "Linux 环境不支持在线升级，请更新镜像", "stage": "launch"}
            return
    except OSError as e:
        yield {"ok": False, "error": f"Cannot start upgrade script: {e}", "stage": "launch"}
        return

    result = {"ok": True, "stage": "launched", "new_version": new_version, "message": "即将重启..."}
    if conflicts:
        result["workspace_warning"] = (
            f"New zip contains protected user data files. "
            f"Upgrade script will backup and restore: {', '.join(conflicts)}"
        )
    yield result


def perform_upgrade(download_url: str) -> dict:
    """Synchronous wrapper — collects generator output into a single result dict."""
    result = {}
    for update in perform_upgrade_progress(download_url):
        result = update
    return result
