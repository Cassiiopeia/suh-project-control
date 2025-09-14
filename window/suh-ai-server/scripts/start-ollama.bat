@echo off
REM 한국어 출력을 위한 코드페이지 설정
chcp 65001 >nul 2>&1
REM Ollama 서버 시작 스크립트

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%.."
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "MAIN_LOG=%LOG_DIR%\server.log"

REM Ollama 실행 파일 경로 (자동 감지)
set "OLLAMA_EXE="
if exist "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama.exe" (
    set "OLLAMA_EXE=C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama.exe"
) else if exist "C:\Program Files\Ollama\ollama.exe" (
    set "OLLAMA_EXE=C:\Program Files\Ollama\ollama.exe"
) else (
    echo ERROR: Ollama 실행 파일을 찾을 수 없습니다!
    echo [%date% %time%] ERROR: Ollama executable not found >> "%MAIN_LOG%"
    exit /b 1
)

echo Ollama 경로: %OLLAMA_EXE%
echo [%date% %time%] Using Ollama: %OLLAMA_EXE% >> "%MAIN_LOG%"

REM 기존 Ollama 프로세스 종료
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo 기존 Ollama 프로세스 종료 중...
    taskkill /F /IM ollama.exe >nul 2>&1
    timeout /t 2 /nobreak > nul
)

REM Ollama 서버 시작
echo Ollama 서버 시작 중...
set OLLAMA_HOST=0.0.0.0:11434
start /min "Ollama Server" "%OLLAMA_EXE%" serve

REM 시작 확인
timeout /t 3 /nobreak > nul
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ Ollama 서버가 성공적으로 시작되었습니다 (포트 11434)
    echo [%date% %time%] Ollama server started successfully on port 11434 >> "%MAIN_LOG%"
) else (
    echo ✗ Ollama 서버 시작 실패!
    echo [%date% %time%] ERROR: Ollama server failed to start >> "%MAIN_LOG%"
    exit /b 1
)
