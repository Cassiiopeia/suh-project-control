@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM Nginx 프록시 서버 시작 스크립트

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

REM Nginx 경로 자동 감지
set "NGINX_PATH="
if exist "C:\tools\nginx-1.29.1\nginx.exe" (
    set "NGINX_PATH=C:\tools\nginx-1.29.1"
) else if exist "C:\nginx\nginx.exe" (
    set "NGINX_PATH=C:\nginx"
) else if exist "C:\Program Files\nginx\nginx.exe" (
    set "NGINX_PATH=C:\Program Files\nginx"
) else (
    echo ERROR: Nginx 실행 파일을 찾을 수 없습니다!
    echo [%date% %time%] ERROR: Nginx executable not found >> "%MAIN_LOG%"
    exit /b 1
)

echo Nginx 경로: %NGINX_PATH%
echo [%date% %time%] Using Nginx: %NGINX_PATH% >> "%MAIN_LOG%"

REM 기존 Nginx 프로세스 정리
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo 기존 Nginx 프로세스 종료 중...
    cd /d "%NGINX_PATH%"
    nginx.exe -s quit >nul 2>&1
    timeout /t 2 /nobreak > nul
    
    REM 강제 종료가 필요한 경우
    tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
    if "%ERRORLEVEL%"=="0" (
        taskkill /F /IM nginx.exe >nul 2>&1
        timeout /t 1 /nobreak > nul
    )
)

REM Nginx 설정 파일 확인
cd /d "%NGINX_PATH%"
nginx.exe -t >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo ERROR: Nginx 설정 파일에 오류가 있습니다!
    echo [%date% %time%] ERROR: Nginx configuration test failed >> "%MAIN_LOG%"
    exit /b 1
)

REM Nginx 서버 시작
echo Nginx 프록시 시작 중...
start /min "Nginx Proxy" nginx.exe

REM 시작 확인
timeout /t 2 /nobreak > nul
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ Nginx 프록시가 성공적으로 시작되었습니다 (포트 11435)
    echo [%date% %time%] Nginx proxy started successfully on port 11435 >> "%MAIN_LOG%"
) else (
    echo ✗ Nginx 프록시 시작 실패!
    echo [%date% %time%] ERROR: Nginx proxy failed to start >> "%MAIN_LOG%"
    exit /b 1
)
