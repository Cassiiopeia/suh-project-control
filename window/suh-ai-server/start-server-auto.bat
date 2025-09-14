@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1

REM Auto-start server with tunnel (no user interaction required)
echo ========================================
echo    AI Server Auto-Start (with Tunnel)
echo ========================================
echo.

REM Get script directory
set "SCRIPT_DIR=%~dp0"

REM Call main server script with auto parameter
call "%SCRIPT_DIR%start-server.bat" auto

echo.
echo Auto-start completed!
echo Press any key to exit...
pause >nul
