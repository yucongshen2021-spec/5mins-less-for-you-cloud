@echo off
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PORT=5739"

set "PYTHON=%~dp0..\..\runtime\python\python.exe"
if not exist "%PYTHON%" set "PYTHON=py -3"

echo [1/2] Cleaning port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING" 2^>nul') do (
    taskkill /F /PID %%a >nul 2>&1
    echo       stopped PID %%a
)
echo [2/2] Starting DNS Capture - http://localhost:%PORT%
cd /d "%~dp0"
start "" http://localhost:%PORT%
%PYTHON% app.py
pause
