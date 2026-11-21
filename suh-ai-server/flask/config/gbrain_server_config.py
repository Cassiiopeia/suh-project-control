"""
gbrain HTTP 서버(MCP) 관리 설정: 서비스 이름, 내부 주소, 설정·로그·관리자 토큰 위치, 게이트 쿠키
값을 바꾸면 함께 바꿀 곳: scripts/setup-gbrain-http.ps1, scripts/gbrain/run-gbrain-http.cmd,
config/nginx.conf(gbrain_backend), config/control_tower/services.yml(gbrain-mcp)
"""
import os

# NSSM 서비스 이름
GBRAIN_SERVICE_NAME = os.environ.get('GBRAIN_SERVICE_NAME', 'gbrain-http')
# gbrain serve --http 내부 주소 (127.0.0.1 바인딩, 외부는 nginx 게이트 경유 /admin 만)
GBRAIN_SERVER_URL = os.environ.get('GBRAIN_SERVER_URL', 'http://127.0.0.1:3131')
# gbrain 설정 루트: {GBRAIN_HOME}/.gbrain/config.json (DB 주소·임베딩 모델)
GBRAIN_HOME = os.environ.get('GBRAIN_HOME', 'C:/Users/kimchi')
# NSSM 이 쓰는 서비스 로그 (stdout·stderr 합침, 10MB 회전)
GBRAIN_LOG_PATH = os.environ.get('GBRAIN_LOG_PATH', 'C:/AI/gbrain/logs/gbrain-http.log')
# 관리자 부트스트랩 토큰 파일 (SYSTEM·Administrators 만 읽기, 값은 절대 기록하지 않음)
GBRAIN_ADMIN_TOKEN_FILE = os.environ.get('GBRAIN_ADMIN_TOKEN_FILE',
                                         'C:/AI/secrets/gbrain-admin-bootstrap-token')

GBRAIN_HTTP_TIMEOUT_SECONDS = 5
GBRAIN_SERVICE_TIMEOUT_SECONDS = 60
# 정지가 이 시간 안에 안 끝나면 NSSM 래퍼 강제 종료 (NSSM 2.24 StopPending 멈춤 대비)
GBRAIN_FORCED_STOP_AFTER_SECONDS = 8
GBRAIN_LOG_DEFAULT_LINES = 200
GBRAIN_LOG_MAX_LINES = 500
# 로그 끝 읽기 상한 (1MB): 회전 전 큰 파일 전체를 읽지 않음
GBRAIN_LOG_TAIL_BYTES = 1024 * 1024

# 관제소 게이트 쿠키: nginx auth_request 가 gbrain /admin 앞에서 검사
GBRAIN_ADMIN_GATE_COOKIE_NAME = 'ct_gbrain_admin_gate'
GBRAIN_ADMIN_GATE_VALID_SECONDS = 12 * 60 * 60


def get_gbrain_config_path() -> str:
    return os.path.join(GBRAIN_HOME, '.gbrain', 'config.json')


def read_admin_token():
    """관리자 토큰 (없거나 못 읽으면 None, 값·경로 내용은 기록하지 않음)"""
    try:
        with open(GBRAIN_ADMIN_TOKEN_FILE, encoding='utf-8') as token_file:
            admin_token = token_file.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return admin_token or None
