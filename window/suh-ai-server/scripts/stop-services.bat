@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM 모든 서비스 중지 스크립트

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

REM silent 모드 확인 (다른 스크립트에서 호출될 때)
set "SILENT_MODE=%1"

if not "%SILENT_MODE%"=="silent" (
    echo ========================================
    echo        서비스 중지 중...
    echo ========================================
    echo.
)

REM Cloudflare Tunnel 중지
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Cloudflare Tunnel 중지 중...
    taskkill /F /IM cloudflared.exe >nul 2>&1
    echo [%date% %time%] Cloudflare Tunnel stopped >> "%MAIN_LOG%"
)

REM Nginx 중지
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Nginx 중지 중...
    
    REM 정상 종료 시도
    for /f "tokens=*" %%i in ('where nginx.exe 2^>nul') do (
        pushd "%%~dpi"
        nginx.exe -s quit >nul 2>&1
        popd
        goto nginx_quit_done
    )
    
    :nginx_quit_done
    timeout /t 2 /nobreak > nul
    
    REM 강제 종료
    tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
    if "%ERRORLEVEL%"=="0" (
        taskkill /F /IM nginx.exe >nul 2>&1
    )
    echo [%date% %time%] Nginx stopped >> "%MAIN_LOG%"
)

REM Ollama 중지
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    if not "%SILENT_MODE%"=="silent" echo Ollama 중지 중...
    taskkill /F /IM ollama.exe >nul 2>&1
    echo [%date% %time%] Ollama stopped >> "%MAIN_LOG%"
)

REM 포트 해제 대기
timeout /t 2 /nobreak > nul

if not "%SILENT_MODE%"=="silent" (
    echo.
    echo ✓ 모든 서비스가 중지되었습니다.
    echo [%date% %time%] All services stopped >> "%MAIN_LOG%"
)
