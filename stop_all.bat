@echo off
echo ============================================
echo   Stop All Services
echo ============================================
echo.
for %%p in (7000 7001 7002 7003 7004) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p " ^| findstr "LISTENING" 2^>nul') do (
        echo   Stopping port %%p (PID %%a)
        taskkill /F /PID %%a >nul 2>&1
    )
)
echo.
echo   All services stopped.
echo ============================================
goto :eof
