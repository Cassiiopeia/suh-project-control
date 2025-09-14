@echo off
REM AI Server 설정 파일
REM 이 파일을 수정하여 서버 설정을 변경할 수 있습니다

REM ===== 기본 경로 설정 =====
REM Ollama 실행 파일 경로 (자동 감지되지 않을 경우 수동 설정)
REM set "OLLAMA_EXE_PATH=C:\Program Files\Ollama\ollama.exe"

REM Nginx 설치 경로 (자동 감지되지 않을 경우 수동 설정)
REM set "NGINX_PATH=C:\nginx"

REM ===== 포트 설정 =====
set "OLLAMA_PORT=11434"
set "NGINX_PROXY_PORT=11435"
set "NGINX_HTTP_PORT=80"

REM ===== API 키 설정 =====
set "API_KEY=Kimchi123@"

REM ===== 로그 설정 =====
set "LOG_LEVEL=INFO"
set "MAX_LOG_SIZE=10MB"
set "LOG_RETENTION_DAYS=30"

REM ===== 터널 설정 =====
set "TUNNEL_AUTO_START=false"
set "TUNNEL_TIMEOUT=30"

REM ===== 기타 설정 =====
set "AUTO_RESTART_ON_FAIL=true"
set "STARTUP_DELAY=3"
