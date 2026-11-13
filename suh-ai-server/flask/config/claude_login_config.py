"""
Claude 로그인 6자리 코드 조회 설정: 대기·유효시간 상수, 계정 암호화 비밀 문구(환경변수)
계정(Gmail 주소·앱 비밀번호)은 DB claude_login_account 에서 관리
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

# 관제소 알림 허브: 코드 발급·열람 알림을 받는 프로젝트 ID와 알림 종류
CONTROL_TOWER_PROJECT_ID = "suh-ai"
CONTROL_TOWER_EVENT_KIND = "claude-code"
# 알림 필드: 브라우저(User-Agent) 표시 최대 글자 수
EVENT_USER_AGENT_MAX_LENGTH = 60

# .env: 앱 비밀번호 암호화 비밀 문구 (DB 밖 보관, 서버 이전 시 같은 값으로 복호화)
ENV_ACCOUNT_SECRET = "CLAUDE_LOGIN_ACCOUNT_SECRET"


def get_account_secret():
    return os.environ.get(ENV_ACCOUNT_SECRET) or None


def is_secret_configured() -> bool:
    return bool(get_account_secret())
