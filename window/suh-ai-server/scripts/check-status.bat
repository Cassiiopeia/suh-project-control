@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1
REM Service status check script

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

echo ========================================
echo        Service Status Check
echo ========================================
echo.

REM Check Ollama status
echo [Ollama Server]
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Running
    netstat -an | findstr :11434 | findstr LISTENING >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo [OK] Port 11434 listening
        echo [%date% %time%] Ollama: Running, Port 11434 OK >> "%MAIN_LOG%"
    ) else (
        echo [ERROR] Port 11434 not listening
        echo [%date% %time%] Ollama: Running, Port 11434 NOT listening >> "%MAIN_LOG%"
    )
) else (
    echo [ERROR] Not running
    echo [%date% %time%] Ollama: NOT running >> "%MAIN_LOG%"
)

echo.

REM Check Nginx status
echo [Nginx Proxy]
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Running
    netstat -an | findstr :11435 | findstr LISTENING >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo [OK] Port 11435 listening
        echo [%date% %time%] Nginx: Running, Port 11435 OK >> "%MAIN_LOG%"
    ) else (
        echo [ERROR] Port 11435 not listening
        echo [%date% %time%] Nginx: Running, Port 11435 NOT listening >> "%MAIN_LOG%"
    )
) else (
    echo [ERROR] Not running
    echo [%date% %time%] Nginx: NOT running >> "%MAIN_LOG%"
)

echo.

REM Check Cloudflare Tunnel status
echo [Cloudflare Tunnel]
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Running
    if exist "%PROJECT_ROOT%\data\tunnel_url.txt" (
        echo [OK] Tunnel URL available
        set /p TUNNEL_URL=<"%PROJECT_ROOT%\data\tunnel_url.txt"
        echo   URL: %TUNNEL_URL%
        echo [%date% %time%] Tunnel: Running, URL available >> "%MAIN_LOG%"
    ) else (
        echo [WAIT] Tunnel URL pending...
        echo [%date% %time%] Tunnel: Running, URL pending >> "%MAIN_LOG%"
    )
) else (
    echo [ERROR] Not running
    echo [%date% %time%] Tunnel: NOT running >> "%MAIN_LOG%"
)

echo.
echo ========================================

REM Display connection info
echo.
echo [Local Access]
echo - Ollama Direct: http://localhost:11434
echo - Nginx Proxy: http://localhost:11435
echo.

if exist "%PROJECT_ROOT%\data\tunnel_url.txt" (
    set /p TUNNEL_URL=<"%PROJECT_ROOT%\data\tunnel_url.txt"
    echo [External Access]
    echo - Cloudflare Tunnel: %TUNNEL_URL%
    echo - API Key: X-API-Key: Kimchi123@
    echo.
)