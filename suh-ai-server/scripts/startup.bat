@echo off
REM ========================================
REM SUH-AI-Server Startup Script
REM Author: Claude AI
REM Description: Starts Ollama and Nginx services
REM ========================================

echo.
echo ========================================
echo SUH-AI-Server Startup Script
echo ========================================
echo.

REM 1. Ollama 동적 경로 찾기 및 실행
echo [1/2] Starting Ollama...
set "OLLAMA_PATH=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

if exist "%OLLAMA_PATH%" (
    echo    - Ollama found at: %OLLAMA_PATH%

    REM Ollama가 이미 실행 중인지 확인
    tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
    if "%ERRORLEVEL%"=="0" (
        echo    - Ollama is already running
    ) else (
        start "" "%OLLAMA_PATH%" serve
        timeout /t 2 /nobreak >nul
        echo    - Ollama started successfully
    )
) else (
    echo    - ERROR: Ollama not found at %OLLAMA_PATH%
    echo    - Please install Ollama first
)

echo.

REM 2. Nginx 서비스 시작
echo [2/2] Starting Nginx service...

REM 먼저 서비스로 실행 시도
sc query nginx >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo    - Nginx service found
    net start nginx >nul 2>&1
    if %ERRORLEVEL% EQU 0 (
        echo    - Nginx service started successfully
    ) else (
        echo    - Nginx service is already running
    )
) else (
    echo    - Nginx service not found, trying direct execution...

    REM Chocolatey 기본 경로에서 nginx.exe 찾기
    set "NGINX_PATH=C:\tools\nginx-1.29.3\nginx.exe"

    if exist "%NGINX_PATH%" (
        echo    - Nginx found at: %NGINX_PATH%

        REM Nginx가 이미 실행 중인지 확인
        tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
        if "%ERRORLEVEL%"=="0" (
            echo    - Nginx is already running
        ) else (
            start "" "%NGINX_PATH%"
            timeout /t 2 /nobreak >nul
            echo    - Nginx started successfully
        )
    ) else (
        echo    - ERROR: Nginx not found at %NGINX_PATH%
        echo    - Please check nginx installation path
    )
)

echo.
echo ========================================
echo Startup Complete!
echo ========================================
echo.
echo Services Status:
echo - Ollama:      http://localhost:11434
echo - Nginx Proxy: http://localhost:11435
echo.
echo Press any key to exit...
pause >nul
