@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
title AI Server Manager
color 0A

echo ========================================
echo        AI Server Manager v2.0
echo ========================================
echo.

REM 현재 스크립트 경로를 기준으로 작업 디렉토리 설정
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "DATA_DIR=%PROJECT_ROOT%data"
set "CONFIG_DIR=%PROJECT_ROOT%config"

REM 필요한 디렉토리 생성
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"

REM 로그 파일 설정
set "MAIN_LOG=%LOG_DIR%\server.log"
set "ERROR_LOG=%LOG_DIR%\error.log"

REM 시작 로그 기록
echo [%date% %time%] ===== AI Server Startup ===== >> "%MAIN_LOG%"

REM 기존 프로세스 정리
echo [1/4] 기존 프로세스 정리 중...
echo [%date% %time%] Cleaning up existing processes... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\stop-services.bat" silent

REM Ollama 서버 시작
echo [2/4] Ollama 서버 시작 중...
echo [%date% %time%] Starting Ollama server... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\start-ollama.bat"

REM Nginx 프록시 시작
echo [3/4] Nginx 프록시 시작 중...
echo [%date% %time%] Starting Nginx proxy... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\start-nginx.bat"

REM 서비스 상태 확인
echo [4/4] 서비스 상태 확인 중...
echo [%date% %time%] Checking service status... >> "%MAIN_LOG%"
call "%SCRIPT_DIR%scripts\check-status.bat"

echo.
echo ========================================
echo     모든 서비스가 시작되었습니다!
echo ========================================
echo.
echo 로그 확인: %LOG_DIR%
echo 설정 파일: %CONFIG_DIR%
echo 데이터: %DATA_DIR%
echo.

REM 터널 시작 여부 묻기
set /p START_TUNNEL="Cloudflare 터널을 시작하시겠습니까? (y/n): "
if /i "%START_TUNNEL%"=="y" (
    echo.
    echo Cloudflare 터널 시작 중...
    call "%SCRIPT_DIR%scripts\start-tunnel.bat"
)

echo.
echo [%date% %time%] ===== Startup Complete ===== >> "%MAIN_LOG%"

if "%1"=="" (
    echo 종료하려면 아무 키나 누르세요...
    pause >nul
)
