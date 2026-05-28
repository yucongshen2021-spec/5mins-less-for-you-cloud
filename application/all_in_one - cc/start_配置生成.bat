@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PORT=5741"
echo [1/2] Cleaning port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
    echo       stopped PID %%a
)
echo [2/2] Starting Config Gen - http://localhost:%PORT%
cd /d "%~dp0web"
start "" http://localhost:%PORT%
py -3 app.py
pause
