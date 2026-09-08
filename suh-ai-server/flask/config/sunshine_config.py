"""
Sunshine(Moonlight 스트리밍 호스트) 제어 설정
자격증명은 flask/.env 에 두고 요청 시점에 읽는다 — 서비스 기동 후 .env를 채워도
Flask 재시작 없이 반영되게 하기 위함이다.
"""
import os

from dotenv import load_dotenv

# db_config와 같은 .env (이미 로드됐어도 무해)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Sunshine 웹 UI/API — 자체서명 인증서라 verify 없이 localhost로만 호출한다
SUNSHINE_API_URL = os.environ.get('SUNSHINE_API_URL', 'https://127.0.0.1:47990')
# 인증 없는 serverinfo(HTTP 47989) — 스트림 상태(FREE/BUSY)와 실행 중 앱 ID의 유일한 소스
SUNSHINE_SERVERINFO_URL = os.environ.get('SUNSHINE_SERVERINFO_URL', 'http://127.0.0.1:47989/serverinfo')
SUNSHINE_SERVICE_NAME = os.environ.get('SUNSHINE_SERVICE_NAME', 'SunshineService')

# Moonlight 클라이언트가 접속하는 공개 주소 (페이지 안내용)
SUNSHINE_PUBLIC_HOST = 'suh-project.synology.me'

SUNSHINE_API_TIMEOUT_SECONDS = 5
SUNSHINE_SERVICE_TIMEOUT_SECONDS = 30
SUNSHINE_LOG_MAX_LINES = 500

# serverinfo의 currentgame 은 앱 ID만 준다. ID 산출 규칙(Sunshine 내부 해시)을 재현할 수 없어
# 페어링된 클라이언트의 applist 로 확인한 값을 표에 둔다. 없는 ID는 원문 그대로 표시한다.
SUNSHINE_KNOWN_APP_IDS = {
    '881448767': 'Desktop',
    '1093255277': 'Steam Big Picture',
}


def get_web_credentials():
    """(user, password) — 둘 중 하나라도 비어 있으면 미설정으로 본다"""
    return (os.environ.get('SUNSHINE_WEB_USER', '').strip(),
            os.environ.get('SUNSHINE_WEB_PASSWORD', ''))
