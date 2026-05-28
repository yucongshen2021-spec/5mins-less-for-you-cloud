@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PORT=5742"
echo [1/2] Cleaning port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
    echo       stopped PID %%a
)
echo [2/2] Starting Config Analyzer - http://localhost:%PORT%/er_config_analyzer.html
cd /d "%~dp0"
start "" http://localhost:%PORT%/er_config_analyzer.html
py -3 -m http.server %PORT%
pause
