@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM 서비스 상태 확인 스크립트

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

echo ========================================
echo        서비스 상태 확인
echo ========================================
echo.

REM Ollama 상태 확인
echo [Ollama 서버]
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ 실행 중
    netstat -an | findstr :11434 | findstr LISTENING >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo ✓ 포트 11434 리스닝 중
        echo [%date% %time%] Ollama: Running, Port 11434 OK >> "%MAIN_LOG%"
    ) else (
        echo ✗ 포트 11434 리스닝 안됨
        echo [%date% %time%] Ollama: Running, Port 11434 NOT listening >> "%MAIN_LOG%"
    )
) else (
    echo ✗ 실행 안됨
    echo [%date% %time%] Ollama: NOT running >> "%MAIN_LOG%"
)

echo.

REM Nginx 상태 확인
echo [Nginx 프록시]
tasklist /FI "IMAGENAME eq nginx.exe" 2>NUL | find /I /N "nginx.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ 실행 중
    netstat -an | findstr :11435 | findstr LISTENING >nul 2>&1
    if "%ERRORLEVEL%"=="0" (
        echo ✓ 포트 11435 리스닝 중
        echo [%date% %time%] Nginx: Running, Port 11435 OK >> "%MAIN_LOG%"
    ) else (
        echo ✗ 포트 11435 리스닝 안됨
        echo [%date% %time%] Nginx: Running, Port 11435 NOT listening >> "%MAIN_LOG%"
    )
) else (
    echo ✗ 실행 안됨
    echo [%date% %time%] Nginx: NOT running >> "%MAIN_LOG%"
)

echo.

REM Cloudflare Tunnel 상태 확인
echo [Cloudflare Tunnel]
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ 실행 중
    if exist "%PROJECT_ROOT%\data\tunnel_url.txt" (
        echo ✓ 터널 URL 생성됨
        set /p TUNNEL_URL=<"%PROJECT_ROOT%\data\tunnel_url.txt"
        echo   URL: %TUNNEL_URL%
        echo [%date% %time%] Tunnel: Running, URL available >> "%MAIN_LOG%"
    ) else (
        echo ⚠ 터널 URL 대기 중...
        echo [%date% %time%] Tunnel: Running, URL pending >> "%MAIN_LOG%"
    )
) else (
    echo ✗ 실행 안됨
    echo [%date% %time%] Tunnel: NOT running >> "%MAIN_LOG%"
)

echo.
echo ========================================

REM 접속 정보 표시
echo.
echo [로컬 접속]
echo - Ollama 직접: http://localhost:11434
echo - Nginx 프록시: http://localhost:11435
echo.

if exist "%PROJECT_ROOT%\data\tunnel_url.txt" (
    set /p TUNNEL_URL=<"%PROJECT_ROOT%\data\tunnel_url.txt"
    echo [외부 접속]
    echo - Cloudflare Tunnel: %TUNNEL_URL%
    echo - API 키: X-API-Key: Kimchi123@
    echo.
)
