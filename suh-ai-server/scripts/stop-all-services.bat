@echo off
setlocal

echo ========================================
echo Stopping SUH AI Server Services
echo ========================================
echo.

:: Stop Cloudflare Tunnel
echo Stopping Cloudflare Tunnel...
taskkill /F /IM cloudflared.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Cloudflare Tunnel stopped.
) else (
    echo Cloudflare Tunnel was not running.
)

:: Stop Nginx
echo Stopping Nginx...
nginx -s stop >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Nginx stopped.
) else (
    taskkill /F /IM nginx.exe >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        echo Nginx force stopped.
    ) else (
        echo Nginx was not running.
    )
)

:: Stop Ollama
echo Stopping Ollama...
taskkill /F /IM ollama.exe >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo Ollama stopped.
) else (
    echo Ollama was not running.
)

echo.
echo All services stopped.
pause

endlocal
exit /b 0