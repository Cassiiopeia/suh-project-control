@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1
REM Cloudflare Tunnel startup script

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "DATA_DIR=%PROJECT_ROOT%\data"
set "MAIN_LOG=%LOG_DIR%\server.log"
set "TUNNEL_LOG=%LOG_DIR%\tunnel.log"

echo ========================================
echo      Cloudflare Tunnel Startup
echo ========================================
echo.

REM Stop existing tunnel process
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Stopping existing tunnel process...
    taskkill /F /IM cloudflared.exe >nul 2>&1
    timeout /t 2 /nobreak > nul
)

REM Check cloudflared installation
where cloudflared >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo ERROR: cloudflared is not installed or not in PATH!
    echo.
    echo Installation methods:
    echo 1. https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
    echo 2. Or: winget install cloudflare.cloudflared
    echo.
    echo [%date% %time%] ERROR: cloudflared not found >> "%MAIN_LOG%"
    pause
    exit /b 1
)

echo Starting Cloudflare Tunnel...
echo Waiting for tunnel URL... (max 30 seconds)

REM Start tunnel and capture URL
start /min cmd /c "cloudflared tunnel --url http://localhost:11435 2>&1 | findstr /C:"https://" > "%DATA_DIR%\tunnel_output.txt""

REM Wait for URL generation
set "WAIT_COUNT=0"
:wait_for_url
if exist "%DATA_DIR%\tunnel_output.txt" (
    for /f "tokens=*" %%i in (%DATA_DIR%\tunnel_output.txt) do (
        echo %%i | findstr /C:"https://" >nul
        if not errorlevel 1 (
            echo %%i > "%DATA_DIR%\tunnel_url.txt"
            goto url_found
        )
    )
)

timeout /t 1 /nobreak > nul
set /a WAIT_COUNT+=1
if %WAIT_COUNT% lss 30 goto wait_for_url

echo [WARN] Could not get tunnel URL within 30 seconds.
echo   Tunnel may be running in background.
echo   Check %DATA_DIR%\tunnel_url.txt file later.
echo [%date% %time%] Tunnel started but URL not captured within timeout >> "%MAIN_LOG%"
goto end

:url_found
set /p TUNNEL_URL=<"%DATA_DIR%\tunnel_url.txt"
echo.
echo ========================================
echo        Tunnel Started Successfully!
echo ========================================
echo.
echo External Access URL: %TUNNEL_URL%
echo API Key: X-API-Key: Kimchi123@
echo.
echo Usage example:
echo curl -H "X-API-Key: Kimchi123@" %TUNNEL_URL%/api/tags
echo.

REM Save tunnel info to JSON file
(
echo {
echo   "url": "%TUNNEL_URL%",
echo   "timestamp": "%date% %time%",
echo   "local_endpoint": "http://localhost:11435",
echo   "api_key": "Kimchi123@"
echo }
) > "%DATA_DIR%\tunnel_info.json"

echo [%date% %time%] Tunnel started successfully: %TUNNEL_URL% >> "%MAIN_LOG%"

:end
echo.
echo To stop tunnel, run stop-services.bat