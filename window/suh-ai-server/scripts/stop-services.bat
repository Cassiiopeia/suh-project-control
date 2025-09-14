@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1
REM Stop all services script

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

REM Check for silent mode (when called by other scripts)
set "SILENT_MODE=%1"

if not "%SILENT_MODE%"=="silent" (
    echo ========================================
    echo        Stopping Services...
    echo ========================================
    echo.
)

REM Stop Cloudflare Tunnel
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Stopping Cloudflare Tunnel...
    taskkill /F /IM cloudflared.exe >nul 2>&1
    echo [%date% %time%] Cloudflare Tunnel stopped >> "%MAIN_LOG%"
)

REM Stop Nginx
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Stopping Nginx...
    
    REM Try graceful shutdown first
    for /f "tokens=*" %%i in ('where nginx.exe 2^>nul') do (
        pushd "%%~dpi"
        nginx.exe -s quit >nul 2>&1
        popd
        goto nginx_quit_done
    )
    
    :nginx_quit_done
    timeout /t 2 /nobreak > nul
    
    REM Force kill if still running
    tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
    if "%ERRORLEVEL%"=="0" (
        taskkill /F /IM nginx.exe >nul 2>&1
    )
    echo [%date% %time%] Nginx stopped >> "%MAIN_LOG%"
)

REM Stop Ollama
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Stopping Ollama...
    taskkill /F /IM ollama.exe >nul 2>&1
    echo [%date% %time%] Ollama stopped >> "%MAIN_LOG%"
)

REM Wait for port release
timeout /t 2 /nobreak > nul

if not "%SILENT_MODE%"=="silent" (
    echo.
    echo [OK] All services stopped.
    echo [%date% %time%] All services stopped >> "%MAIN_LOG%"
)