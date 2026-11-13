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
# .env: 관제소 비밀값 원본 (DB 발급 이벤트 토큰 해시 키·받을 곳 URL 암호화 키 파생, 없으면 발급·DB 토큰 검증·받을 곳 등록·발송 불가)
# 한 번 정하면 바꾸지 않음: 바꾸면 DB 발급 토큰 전부 즉시 401 > 관리 화면 프로젝트 토큰 모두 재발급·재배포 필요,
# 받을 곳 URL도 복호화 불가 > 모두 다시 등록 필요
CONTROL_TOWER_SECRET_ENV = "CONTROL_TOWER_SECRET"
# 토큰 교체 후 이전 토큰 유효 기간 (일, 교체된 토큰마다 각자)
PREVIOUS_EVENT_TOKEN_VALID_DAYS = 7
# 프로젝트당 유예 중 이전 토큰 최대 개수 (넘으면 만료가 가장 이른 것부터 즉시 삭제)
MAX_PREVIOUS_EVENT_TOKEN_COUNT = 3
