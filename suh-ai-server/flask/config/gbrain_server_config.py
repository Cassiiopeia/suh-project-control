"""
gbrain HTTP 서버(MCP) 관리 설정: 서비스 이름, 내부 주소, 설정·로그·관리자 토큰 위치, 게이트 쿠키
값을 바꾸면 함께 바꿀 곳: scripts/setup-gbrain-http.ps1, scripts/gbrain/run-gbrain-http.cmd,
config/nginx.conf(gbrain_backend, team_brain_upstream), config/control_tower/services.yml(gbrain-mcp, gbrain-team-*)
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

# MCP 기기 토큰 관리 (#207): 기기에 넣을 공개 주소 (nginx location = /mcp, #204)
GBRAIN_PUBLIC_MCP_URL = os.environ.get('GBRAIN_PUBLIC_MCP_URL', 'https://ai.suhsaechan.kr/mcp')
# gbrain 소유자 세션 재사용 시간: gbrain 세션 24시간보다 짧게 (만료 직전 요청 실패 방지)
GBRAIN_OWNER_SESSION_REUSE_SECONDS = 23 * 60 * 60


# ---------- 팀 브레인 (#210): 프로젝트마다 gbrain HTTP 서버 1개 ----------
# 팀 브레인 루트: {root}/team-brains.json(등록부), {root}/<project>/.gbrain/config.json, {root}/nginx/<project>.map
GBRAIN_TEAM_ROOT = os.environ.get('GBRAIN_TEAM_ROOT', 'C:/AI/gbrain/teams')
# NSSM 서비스 이름: gbrain-team-<project>
GBRAIN_TEAM_SERVICE_PREFIX = 'gbrain-team-'
# 내부 포트 범위 (3131 은 개인 브레인), 127.0.0.1 바인딩
GBRAIN_TEAM_PORT_FIRST = 3141
GBRAIN_TEAM_PORT_LAST = 3199
# 관리자 토큰 파일: C:/AI/secrets/gbrain-team-<project>-admin-token (브레인마다 따로)
GBRAIN_SECRETS_DIR = os.environ.get('GBRAIN_SECRETS_DIR', 'C:/AI/secrets')
# 공개 주소 바탕: {base}/team/<project>/mcp (nginx location ~ ^/team/<project>/mcp$)
GBRAIN_PUBLIC_BASE_URL = os.environ.get('GBRAIN_PUBLIC_BASE_URL', 'https://ai.suhsaechan.kr')
# Claude Code MCP 서버 이름: 개인 gbrain, 팀 gbrain-<project> (도구 이름 mcp__gbrain-<project>__* 로 분리)
GBRAIN_PERSONAL_MCP_SERVER_NAME = 'gbrain'
GBRAIN_TEAM_MCP_SERVER_PREFIX = 'gbrain-'
# 팀 브레인 프로젝트 키: 소문자 시작, 소문자·숫자 2~20자 (DB gbrain_<key>, 계정 <key>_writer 규칙과 맞춤)
GBRAIN_TEAM_PROJECT_PATTERN = r'^[a-z][a-z0-9]{1,19}$'
# 설치 도구 위치 (개인 브레인 setup-gbrain-http.ps1 이 설치한 bun·gbrain 을 같이 씀)
GBRAIN_BUN_HOME = os.environ.get('GBRAIN_BUN_HOME', GBRAIN_HOME)
GBRAIN_SETUP_SCRIPT_PATH = os.environ.get(
    'GBRAIN_SETUP_SCRIPT_PATH',
    os.path.join(os.path.dirname(__file__), '..', '..', 'scripts', 'setup-gbrain-http.ps1'))
# nginx 설치 폴더 후보 (deploy-nginx.ps1 과 같은 규칙: C:/tools/nginx-*)
GBRAIN_NGINX_GLOB = os.environ.get('GBRAIN_NGINX_GLOB', 'C:/tools/nginx-*')
# 서비스 설치·초기화 제한 시간 (기동 후 /health 60초 대기 포함)
GBRAIN_TEAM_SETUP_TIMEOUT_SECONDS = 180
GBRAIN_TEAM_INIT_TIMEOUT_SECONDS = 120


def get_gbrain_config_path(gbrain_home=None) -> str:
    """{gbrain_home 또는 개인 GBRAIN_HOME}/.gbrain/config.json"""
    return os.path.join(gbrain_home or GBRAIN_HOME, '.gbrain', 'config.json')


def read_admin_token(token_file=None):
    """관리자 토큰 (없거나 못 읽으면 None, 값·경로 내용은 기록하지 않음), token_file 없으면 개인 브레인 토큰"""
    try:
        with open(token_file or GBRAIN_ADMIN_TOKEN_FILE, encoding='utf-8') as admin_token_stream:
            admin_token = admin_token_stream.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return admin_token or None
