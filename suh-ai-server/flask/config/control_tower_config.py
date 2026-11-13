"""
관제소(서비스 감시) 설정: 등록 파일·DB 경로, 점검 주기, 환경변수 이름
"""
import os

_FLASK_ROOT_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# 등록 파일 (서비스·프로젝트·디스코드 정책의 단일 원본)
REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "control_tower", "services.yml")
# 감시 데이터 SQLite (Windows 로컬, 레포 제외)
DATABASE_PATH = os.path.join(_FLASK_ROOT_DIRECTORY, "data", "control_tower.db")

# 점검 간격 (초)
POLL_INTERVAL_SECONDS = 60
# Worker 외부 점검 대상 상한 (Cloudflare 무료 플랜 서브요청 50회 중 여유분 제외)
MAX_EXTERNAL_CHECKS = 45

# .env: Worker 주소 / 심박·스냅샷 서명 비밀키 (Worker secret과 같은 값)
WORKER_URL_ENV = "CONTROL_TOWER_WORKER_URL"
HMAC_SECRET_ENV = "CONTROL_TOWER_HMAC_SECRET"
# .env: 디스코드 봇 토큰 / 관제소 서버(길드) ID
DISCORD_BOT_TOKEN_ENV = "DISCORD_BOT_TOKEN"
DISCORD_GUILD_ID_ENV = "DISCORD_GUILD_ID"
# .env: 프로젝트별 이벤트 토큰 접두사 (CONTROL_EVENT_TOKEN_<PROJECT_ID 대문자, '-' > '_'>)
EVENT_TOKEN_ENV_PREFIX = "CONTROL_EVENT_TOKEN_"
# .env: 관제소 비밀값 원본 (DB 발급 이벤트 토큰 해시 키 파생, 없으면 발급·DB 토큰 검증 불가)
CONTROL_TOWER_SECRET_ENV = "CONTROL_TOWER_SECRET"
# 토큰 교체 후 이전 토큰 유효 기간 (일)
PREVIOUS_EVENT_TOKEN_VALID_DAYS = 7
