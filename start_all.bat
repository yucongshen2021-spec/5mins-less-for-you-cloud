@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"
echo ============================================
echo   Network Tools Portal
echo ============================================
echo.
echo   [1/2] Cleaning old processes...
for %%p in (5741 5740 5739 5742 5000) do call :kill_port %%p
echo   [2/2] Starting all services...
echo.
echo   Portal:      http://localhost:5000
echo   Config Gen:  http://localhost:5741
echo   Test Report: http://localhost:5740
echo   DNS Capture: http://localhost:5739
echo   Config Ana:  http://localhost:5742
echo.
echo   Press Ctrl+C to stop all.
echo ============================================
echo.
cd /d "%~dp0application\portal"
py -3 app.py
pause
goto :eof

:kill_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1" ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
exit /b
