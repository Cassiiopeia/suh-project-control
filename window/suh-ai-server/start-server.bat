@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1

REM Set console font to support UTF-8 (if possible)
for /f "tokens=2 delims=:" %%a in ('chcp') do set "ORIGINAL_CP=%%a"
set "ORIGINAL_CP=%ORIGINAL_CP: =%"

title AI Server Manager
color 0A

echo ========================================
echo        AI Server Manager v2.0
echo ========================================
echo.

REM Set working directories based on script location
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "DATA_DIR=%PROJECT_ROOT%data"
set "CONFIG_DIR=%PROJECT_ROOT%config"

REM Create necessary directories
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

REM Set log file paths
set "MAIN_LOG=%LOG_DIR%\server.log"
set "ERROR_LOG=%LOG_DIR%\error.log"

REM Log startup
echo [%date% %time%] ===== AI Server Startup ===== >> "%MAIN_LOG%"

REM Step 1: Clean up existing processes
echo [1/4] Cleaning up existing processes...
echo [%date% %time%] Cleaning up existing processes... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\stop-services.bat" silent

REM Step 2: Start Ollama server
echo [2/4] Starting Ollama server...
echo [%date% %time%] Starting Ollama server... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\start-ollama.bat"

REM Step 3: Start Nginx proxy
echo [3/4] Starting Nginx proxy...
echo [%date% %time%] Starting Nginx proxy... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\start-nginx.bat"

REM Step 4: Check service status
echo [4/4] Checking service status...
echo [%date% %time%] Checking service status... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\check-status.bat"

echo.
echo ========================================
echo     All services started successfully!
echo ========================================
echo.
echo Log directory: %LOG_DIR%
echo Config directory: %CONFIG_DIR%
echo Data directory: %DATA_DIR%
echo.

REM Ask about tunnel startup
set /p START_TUNNEL="Start Cloudflare tunnel? (y/n): "
if /i "%START_TUNNEL%"=="y" (
    echo.
    echo Starting Cloudflare tunnel...
    call "%SCRIPT_DIR%scripts\start-tunnel.bat"
)

echo.
echo [%date% %time%] ===== Startup Complete ===== >> "%MAIN_LOG%"

if "%1"=="" (
    echo Press any key to exit...
    pause >nul
)