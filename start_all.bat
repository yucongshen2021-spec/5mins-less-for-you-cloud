@echo off
cd /d "%~dp0"

rem Use bundled Python runtime if present (customer package), otherwise system py -3
set "PYTHON=%~dp0runtime\python\python.exe"
if exist "%PYTHON%" (
    set "PYTHONNOUSERSITE=1"
    set "RELEASE_MODE=1"
) else (
    set "PYTHON=py -3"
)

echo ============================================
echo   Network Tools Portal
echo ============================================
echo.
echo   Using bundled Python runtime
echo.
echo   [1/3] Cleaning old processes...
for %%p in (5003 5002 5001 5004 5000 7003 7002 7001 7004 7000 8000) do call :kill_port %%p
echo   [2/3] Starting update mirror on port 8000...
set "BUNDLE_DIR=%~dp0"
if exist "%BUNDLE_DIR%dist" (
    start "5mins Update Mirror" /min "%PYTHON%" "%BUNDLE_DIR%tools\serve_mirror.py" --port 8000 --dist "%BUNDLE_DIR%dist"
    echo     Mirror started — providing update service on port 8000
) else (
    echo     WARNING: dist/ directory not found, mirror not started
)
echo   [3/3] Starting all services...
echo.
if defined RELEASE_MODE (
    echo   Portal:      http://localhost:7000
    echo   Config Gen:  http://localhost:7000/app/all_in_one/
    echo   Test Report: http://localhost:7000/app/test_report/
    echo   DNS Capture: http://localhost:7000/app/domain_capture/
    echo   Config Ana:  http://localhost:7000/app/config_analyzer/
) else (
    echo   Portal:      http://localhost:5000
    echo   Config Gen:  http://localhost:5000/app/all_in_one/
    echo   Test Report: http://localhost:5000/app/test_report/
    echo   DNS Capture: http://localhost:5000/app/domain_capture/
    echo   Config Ana:  http://localhost:5000/app/config_analyzer/
)
echo.
echo   Press Ctrl+C to stop all.
echo ============================================
echo.
cd /d "%~dp0application\portal"
%PYTHON% app.py
goto :eof

:kill_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
exit /b
