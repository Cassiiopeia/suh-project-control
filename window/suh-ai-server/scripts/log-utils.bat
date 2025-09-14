@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM 로그 유틸리티 스크립트

REM 이 스크립트는 다른 스크립트에서 call로 호출됩니다
REM 사용법: call log-utils.bat "INFO" "메시지" [로그파일경로]

set "LOG_LEVEL=%~1"
set "LOG_MESSAGE=%~2"
set "LOG_FILE=%~3"

REM 기본 로그 파일 설정
if "%LOG_FILE%"=="" (
    set "SCRIPT_DIR=%~dp0"
    set "PROJECT_ROOT=%SCRIPT_DIR%.."
    set "LOG_FILE=%PROJECT_ROOT%\logs\server.log"
)

REM 타임스탬프 생성
for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set "LOG_DATE=%%d-%%b-%%c"
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set "LOG_TIME=%%a:%%b"

REM 로그 레벨별 색상 및 아이콘
if /i "%LOG_LEVEL%"=="INFO" (
    set "LOG_COLOR=0A"
    set "LOG_ICON=ℹ"
) else if /i "%LOG_LEVEL%"=="SUCCESS" (
    set "LOG_COLOR=0A"
    set "LOG_ICON=✓"
) else if /i "%LOG_LEVEL%"=="WARNING" (
    set "LOG_COLOR=0E"
    set "LOG_ICON=⚠"
) else if /i "%LOG_LEVEL%"=="ERROR" (
    set "LOG_COLOR=0C"
    set "LOG_ICON=✗"
) else (
    set "LOG_COLOR=07"
    set "LOG_ICON=•"
)

REM 콘솔 출력 (색상 적용)
color %LOG_COLOR%
echo %LOG_ICON% %LOG_MESSAGE%
color 07

REM 파일 로그 (UTF-8 인코딩으로 저장)
echo [%LOG_DATE% %LOG_TIME%] [%LOG_LEVEL%] %LOG_MESSAGE% >> "%LOG_FILE%"

REM 에러 로그는 별도 파일에도 저장
if /i "%LOG_LEVEL%"=="ERROR" (
    set "ERROR_LOG=%PROJECT_ROOT%\logs\error.log"
    echo [%LOG_DATE% %LOG_TIME%] %LOG_MESSAGE% >> "%ERROR_LOG%"
)
