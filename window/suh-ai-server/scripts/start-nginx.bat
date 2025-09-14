@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1
REM Nginx proxy server startup script

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

REM Auto-detect Nginx path
set "NGINX_PATH="
if exist "C:\tools\nginx-1.29.1\nginx.exe" (
    set "NGINX_PATH=C:\tools\nginx-1.29.1"
) else if exist "C:\nginx\nginx.exe" (
    set "NGINX_PATH=C:\nginx"
) else if exist "C:\Program Files\nginx\nginx.exe" (
    set "NGINX_PATH=C:\Program Files\nginx"
) else (
    echo ERROR: Nginx executable not found!
    echo [%date% %time%] ERROR: Nginx executable not found >> "%MAIN_LOG%"
    exit /b 1
)

echo Nginx path: %NGINX_PATH%
echo [%date% %time%] Using Nginx: %NGINX_PATH% >> "%MAIN_LOG%"

REM Stop existing Nginx processes
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Stopping existing Nginx process...
    cd /d "%NGINX_PATH%"
    nginx.exe -s quit >nul 2>&1
    timeout /t 2 /nobreak > nul
    
    REM Force kill if necessary
    tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
    if "%ERRORLEVEL%"=="0" (
        taskkill /F /IM nginx.exe >nul 2>&1
        timeout /t 1 /nobreak > nul
    )
)

REM Test Nginx configuration
cd /d "%NGINX_PATH%"
nginx.exe -t >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo ERROR: Nginx configuration test failed!
    echo [%date% %time%] ERROR: Nginx configuration test failed >> "%MAIN_LOG%"
    exit /b 1
)

REM Start Nginx server
echo Starting Nginx proxy...
start /min "Nginx Proxy" nginx.exe

REM Verify startup
timeout /t 2 /nobreak > nul
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Nginx proxy started successfully (port 11435)
    echo [%date% %time%] Nginx proxy started successfully on port 11435 >> "%MAIN_LOG%"
) else (
    echo [ERROR] Nginx proxy failed to start!
    echo [%date% %time%] ERROR: Nginx proxy failed to start >> "%MAIN_LOG%"
    exit /b 1
)