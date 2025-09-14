@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM Cloudflare Tunnel 시작 스크립트

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "DATA_DIR=%PROJECT_ROOT%\data"
set "MAIN_LOG=%LOG_DIR%\server.log"
set "TUNNEL_LOG=%LOG_DIR%\tunnel.log"

echo ========================================
echo      Cloudflare Tunnel 시작
echo ========================================
echo.

REM 기존 터널 프로세스 종료
tasklist /FI "IMAGENAME eq cloudflared.exe" 2>NUL | find /I /N "cloudflared.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo 기존 터널 프로세스 종료 중...
    taskkill /F /IM cloudflared.exe >nul 2>&1
    timeout /t 2 /nobreak > nul
)

REM cloudflared 설치 확인
where cloudflared >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo ERROR: cloudflared가 설치되지 않았거나 PATH에 없습니다!
    echo.
    echo 설치 방법:
    echo 1. https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/
    echo 2. 또는 winget install cloudflare.cloudflared
    echo.
    echo [%date% %time%] ERROR: cloudflared not found >> "%MAIN_LOG%"
    pause
    exit /b 1
)

echo Cloudflare Tunnel 시작 중...
echo 터널 URL을 기다리는 중... (최대 30초)

REM 터널 시작 및 URL 캡처
start /min cmd /c "cloudflared tunnel --url http://localhost:11435 2>&1 | findstr /C:"https://" > "%DATA_DIR%\tunnel_output.txt""

REM URL이 생성될 때까지 대기
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

echo ⚠ 터널 URL을 30초 내에 가져올 수 없었습니다.
echo   터널이 백그라운드에서 실행 중일 수 있습니다.
echo   나중에 %DATA_DIR%\tunnel_url.txt 파일을 확인해보세요.
echo [%date% %time%] Tunnel started but URL not captured within timeout >> "%MAIN_LOG%"
goto end

:url_found
set /p TUNNEL_URL=<"%DATA_DIR%\tunnel_url.txt"
echo.
echo ========================================
echo        터널이 성공적으로 시작됨!
echo ========================================
echo.
echo 🌐 외부 접속 URL: %TUNNEL_URL%
echo 🔑 API 키: X-API-Key: Kimchi123@
echo.
echo 사용 예시:
echo curl -H "X-API-Key: Kimchi123@" %TUNNEL_URL%/api/tags
echo.

REM 터널 정보를 JSON 파일로 저장
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
echo 터널을 중지하려면 stop-services.bat을 실행하세요.
