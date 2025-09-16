@echo off
setlocal enabledelayedexpansion

:: SUH AI Server Auto Startup Script
echo ========================================
echo SUH AI Server Auto Startup
echo ========================================
echo.

:: Set paths
set "BASE_DIR=%~dp0.."
set "CONFIG_DIR=%BASE_DIR%\config"
set "LOGS_DIR=%BASE_DIR%\logs"
set "DATA_DIR=%BASE_DIR%\data"
set "SCRIPTS_DIR=%BASE_DIR%\scripts"

:: Create log file with timestamp
for /f "tokens=2 delims==" %%a in ('wmic OS Get localdatetime /value') do set "dt=%%a"
set "YY=%dt:~2,2%" & set "YYYY=%dt:~0,4%" & set "MM=%dt:~4,2%" & set "DD=%dt:~6,2%"
set "HH=%dt:~8,2%" & set "Min=%dt:~10,2%" & set "Sec=%dt:~12,2%"
set "LOG_FILE=%LOGS_DIR%\startup_%YYYY%%MM%%DD%_%HH%%Min%%Sec%.log"

:: Ensure directories exist
if not exist "%LOGS_DIR%" mkdir "%LOGS_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

echo [%date% %time%] Starting SUH AI Server components... >> "%LOG_FILE%"

:: Function to check if process is running
:check_process
set "process_name=%~1"
tasklist /FI "IMAGENAME eq %process_name%" 2>NUL | find /I /N "%process_name%">NUL
exit /b %ERRORLEVEL%

:: 1. Start Ollama if not running
echo Checking Ollama status...
call :check_process "ollama.exe"
if %ERRORLEVEL% neq 0 (
    echo Starting Ollama...
    echo [%date% %time%] Starting Ollama... >> "%LOG_FILE%"
    start /B ollama serve >> "%LOGS_DIR%\ollama.log" 2>&1
    timeout /t 5 /nobreak > nul
    echo Ollama started.
    echo [%date% %time%] Ollama started successfully >> "%LOG_FILE%"
) else (
    echo Ollama is already running.
    echo [%date% %time%] Ollama already running >> "%LOG_FILE%"
)

:: 2. Start Nginx if not running
echo Checking Nginx status...
call :check_process "nginx.exe"
if %ERRORLEVEL% neq 0 (
    echo Starting Nginx...
    echo [%date% %time%] Starting Nginx... >> "%LOG_FILE%"
    
    :: Check if nginx is installed via choco
    where nginx >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        cd /d "%BASE_DIR%"
        start /B nginx -c "%CONFIG_DIR%\nginx.conf" >> "%LOGS_DIR%\nginx.log" 2>&1
    ) else (
        echo Nginx not found. Please install using: choco install nginx
        echo [%date% %time%] ERROR: Nginx not found >> "%LOG_FILE%"
    )
    
    timeout /t 3 /nobreak > nul
    echo Nginx started.
    echo [%date% %time%] Nginx started successfully >> "%LOG_FILE%"
) else (
    echo Nginx is already running.
    echo [%date% %time%] Nginx already running >> "%LOG_FILE%"
)

:: 3. Start Cloudflare Tunnel
echo Starting Cloudflare Tunnel...
echo [%date% %time%] Starting Cloudflare Tunnel... >> "%LOG_FILE%"

:: Kill existing cloudflared processes
taskkill /F /IM cloudflared.exe >nul 2>&1

:: Check if cloudflared is installed
where cloudflared >nul 2>&1
if %ERRORLEVEL% equ 0 (
    :: Start tunnel and capture info
    call "%SCRIPTS_DIR%\start-cloudflare-tunnel.bat"
    echo Cloudflare Tunnel started.
    echo [%date% %time%] Cloudflare Tunnel started successfully >> "%LOG_FILE%"
) else (
    echo Cloudflared not found. Please install using: choco install cloudflared
    echo [%date% %time%] ERROR: Cloudflared not found >> "%LOG_FILE%"
)

:: 4. Health check
echo.
echo Performing health check...
timeout /t 5 /nobreak > nul

:: Check local Ollama
curl -s http://localhost:11434/api/tags >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Ollama is responding on port 11434
    echo [%date% %time%] Health check: Ollama OK >> "%LOG_FILE%"
) else (
    echo [FAIL] Ollama is not responding
    echo [%date% %time%] Health check: Ollama FAILED >> "%LOG_FILE%"
)

:: Check Nginx proxy
curl -s http://localhost:11435/health >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo [OK] Nginx proxy is responding on port 11435
    echo [%date% %time%] Health check: Nginx OK >> "%LOG_FILE%"
) else (
    echo [FAIL] Nginx proxy is not responding
    echo [%date% %time%] Health check: Nginx FAILED >> "%LOG_FILE%"
)

:: Check if tunnel info exists
if exist "%DATA_DIR%\tunnel-info.json" (
    echo [OK] Cloudflare tunnel configuration found
    echo [%date% %time%] Health check: Tunnel config OK >> "%LOG_FILE%"
) else (
    echo [WARN] Cloudflare tunnel configuration not found
    echo [%date% %time%] Health check: Tunnel config NOT FOUND >> "%LOG_FILE%"
)

echo.
echo ========================================
echo SUH AI Server startup complete!
echo Logs are available at: %LOGS_DIR%
echo ========================================
echo [%date% %time%] Startup sequence completed >> "%LOG_FILE%"

:: Keep window open for 10 seconds to show results
timeout /t 10

endlocal
exit /b 0