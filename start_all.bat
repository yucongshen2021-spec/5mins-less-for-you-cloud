@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

rem 优先用包内便携 Python（客户解压后存在），否则回退到系统 py -3（开发机器）
set "PYTHON=%~dp0runtime\python\python.exe"
if exist "%PYTHON%" (
    set "PYTHONNOUSERSITE=1"
) else (
    set "PYTHON=py -3"
)

echo ============================================
echo   Network Tools Portal
echo ============================================
echo.
echo   Python: %PYTHON%
echo.
echo   [1/2] Cleaning old processes...
for %%p in (5003 5002 5001 5004 5000) do call :kill_port %%p
echo   [2/2] Starting all services...
echo.
echo   Portal:      http://localhost:5000
echo   Config Gen:  http://localhost:5003
echo   Test Report: http://localhost:5002
echo   DNS Capture: http://localhost:5001
echo   Config Ana:  http://localhost:5004
echo.
echo   Press Ctrl+C to stop all.
echo ============================================
echo.
cd /d "%~dp0application\portal"
%PYTHON% app.py
pause
goto :eof

:kill_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
exit /b
