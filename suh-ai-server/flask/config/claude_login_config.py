"""
Claude 로그인 6자리 코드 조회 설정: 대기·유효시간 상수, Gmail 접속 정보(환경변수)
"""
import os

# 메일 폴링 간격 (초)
POLL_INTERVAL_SECONDS = 5
# 메일 대기 최대 시간 (초, 매직링크 유효시간과 동일)
MAIL_WAIT_TIMEOUT_SECONDS = 600
# 작업 시작 전에 도착한 메일도 허용하는 범위 (초, 화면을 늦게 연 경우)
MAIL_ACCEPT_BEFORE_START_SECONDS = 120
# 매직링크·코드 유효시간 (초, 메일 수신 기준)
MAGIC_LINK_VALID_SECONDS = 600
# 링크 페이지에서 코드를 찾는 최대 시간 (초)
CODE_SEARCH_TIMEOUT_SECONDS = 15
# Chromium 설치 위치 고정 (배포 스크립트 설치 <-> NSSM 서비스 실행 계정 공통)
PLAYWRIGHT_BROWSERS_DIRECTORY = r"C:\AI\playwright-browsers"

# .env: Claude 로그인 메일을 받는 Gmail 주소 / 앱 비밀번호(16자리, IMAP 읽기용)
ENV_GMAIL_ADDRESS = "CLAUDE_LOGIN_GMAIL_ADDRESS"
ENV_GMAIL_APP_PASSWORD = "CLAUDE_LOGIN_GMAIL_APP_PASSWORD"


def get_gmail_address():
    return os.environ.get(ENV_GMAIL_ADDRESS) or None


def get_gmail_app_password():
    return os.environ.get(ENV_GMAIL_APP_PASSWORD) or None


def is_configured() -> bool:
    return bool(get_gmail_address() and get_gmail_app_password())
