@echo off
REM Set UTF-8 code page for Korean support
chcp 65001 >nul 2>&1
REM Ollama server startup script

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
    echo ERROR: Ollama executable not found!
    echo [%date% %time%] ERROR: Ollama executable not found >> "%MAIN_LOG%"
    exit /b 1
)

echo Ollama path: %OLLAMA_EXE%
echo [%date% %time%] Using Ollama: %OLLAMA_EXE% >> "%MAIN_LOG%"

REM 기존 Ollama 프로세스 종료
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Stopping existing Ollama process...
    taskkill /F /IM ollama.exe >nul 2>&1
    timeout /t 2 /nobreak > nul
)

REM Ollama 서버 시작
echo Starting Ollama server...
set OLLAMA_HOST=0.0.0.0:11434
start /min "Ollama Server" "%OLLAMA_EXE%" serve

REM 시작 확인
timeout /t 3 /nobreak > nul
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo [OK] Ollama server started successfully (port 11434)
    echo [%date% %time%] Ollama server started successfully on port 11434 >> "%MAIN_LOG%"
) else (
    echo [ERROR] Ollama server failed to start!
    echo [%date% %time%] ERROR: Ollama server failed to start >> "%MAIN_LOG%"
    exit /b 1
)
