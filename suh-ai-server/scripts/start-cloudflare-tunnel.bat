@echo off
setlocal enabledelayedexpansion

:: Cloudflare Quick Tunnel Startup Script with Auto URL Parsing
set "BASE_DIR=%~dp0.."
set "DATA_DIR=%BASE_DIR%\data"
set "LOGS_DIR=%BASE_DIR%\logs"
set "CONFIG_DIR=%BASE_DIR%\config"
set "TEMP_OUTPUT=%TEMP%\cloudflare_output.txt"

:: Ensure directories exist
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"

echo Starting Cloudflare Quick Tunnel (trycloudflare.com)...
echo This will create a temporary public URL for your server.
echo.

:: Kill any existing cloudflared processes
taskkill /F /IM cloudflared.exe >nul 2>&1

:: Start cloudflared tunnel with output capture
echo Starting tunnel and waiting for URL...
start /B powershell -Command "& {cloudflared tunnel --url http://localhost:11435 2>&1 | Tee-Object -FilePath '%TEMP_OUTPUT%' | Tee-Object -FilePath '%LOGS_DIR%\cloudflare.log'}" >nul

:: Wait for tunnel URL to appear (check every second for up to 15 seconds)
set "TUNNEL_URL="
set "ATTEMPTS=0"

:WAIT_FOR_URL
set /a ATTEMPTS+=1
if %ATTEMPTS% gtr 15 (
    echo Timeout waiting for tunnel URL. Check logs for details.
    goto :GENERATE_DEFAULT
)

timeout /t 1 /nobreak >nul

:: Parse the output file for the URL
if exist "%TEMP_OUTPUT%" (
    for /f "tokens=*" %%i in ('findstr "trycloudflare.com" "%TEMP_OUTPUT%" 2^>nul') do (
        set "LINE=%%i"
        :: Extract URL from the line
        for /f "tokens=2 delims=|" %%j in ("!LINE!") do (
            set "RAW_URL=%%j"
            :: Trim spaces
            for /f "tokens=*" %%k in ("!RAW_URL!") do set "TUNNEL_URL=%%k"
        )
    )
)

if not defined TUNNEL_URL goto :WAIT_FOR_URL

echo.
echo ========================================
echo Tunnel URL Found: %TUNNEL_URL%
echo ========================================
echo.

:: Generate tunnel-info.json with parsed URL
:GENERATE_JSON
echo Generating tunnel information...
(
    echo {
    echo   "status": "active",
    echo   "service": "cloudflare-quick-tunnel",
    echo   "timestamp": "%date% %time%",
    echo   "tunnel": {
    echo     "type": "trycloudflare",
    echo     "protocol": "https",
    echo     "url": "%TUNNEL_URL%",
    echo     "local_port": 11435,
    echo     "target": "http://localhost:11434"
    echo   },
    echo   "endpoints": {
    echo     "health": "/health",
    echo     "tunnel_info": "/api/tunnel-info",
    echo     "logs": "/api/logs",
    echo     "ollama": "/"
    echo   },
    echo   "authentication": {
    echo     "required": true,
    echo     "methods": ["Bearer", "X-API-KEY"],
    echo     "local_bypass": true
    echo   },
    echo   "notice": "This is a temporary tunnel via trycloudflare.com. URL may change on restart."
    echo }
) > "%DATA_DIR%\tunnel-info.json"

echo Tunnel information saved to %DATA_DIR%\tunnel-info.json
echo.
echo You can access your AI server at: %TUNNEL_URL%
echo Note: This is a temporary URL that will change when restarted.
goto :END

:GENERATE_DEFAULT
echo Generating default tunnel information...
(
    echo {
    echo   "status": "starting",
    echo   "service": "cloudflare-quick-tunnel",
    echo   "timestamp": "%date% %time%",
    echo   "tunnel": {
    echo     "type": "trycloudflare",
    echo     "protocol": "https",
    echo     "url": "pending",
    echo     "local_port": 11435,
    echo     "target": "http://localhost:11434"
    echo   },
    echo   "notice": "Tunnel is starting. Check logs for URL."
    echo }
) > "%DATA_DIR%\tunnel-info.json"

:END
:: Clean up temp file
if exist "%TEMP_OUTPUT%" del "%TEMP_OUTPUT%"

endlocal
exit /b 0