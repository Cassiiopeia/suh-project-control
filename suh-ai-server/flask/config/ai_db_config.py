"""
AI 서버 공용 PG 관리 설정: 관리 계정 접속 정보(환경변수 > 비밀 파일), 외부 표시 주소
접속 정보는 읽기 실패해도 예외·로그 없이 None (값 자체는 절대 기록하지 않음)
"""
import os

# 환경변수: 관리 계정 DSN 원문 (예: postgresql://ai_db_admin:...@127.0.0.1:5433/postgres)
ENV_ADMIN_URL = "AI_DB_ADMIN_URL"
# 환경변수: DSN 을 담은 파일 경로 (배포가 덮어쓰지 않는 위치)
ENV_ADMIN_URL_FILE = "AI_DB_ADMIN_URL_FILE"
DEFAULT_ADMIN_URL_FILE = "C:/AI/secrets/ai-db-admin-url"
# 환경변수: 연결 문자열에 넣을 외부 주소·포트
ENV_PUBLIC_HOST = "AI_DB_PUBLIC_HOST"
DEFAULT_PUBLIC_HOST = "ai.postgres.suhsaechan.kr"
ENV_PUBLIC_PORT = "AI_DB_PUBLIC_PORT"
DEFAULT_PUBLIC_PORT = 5432


def get_admin_url():
    """관리 DSN: 환경변수 > 파일 (없거나 못 읽으면 None)"""
    url_from_env = (os.environ.get(ENV_ADMIN_URL) or "").strip()
    if url_from_env:
        return url_from_env
    path = os.environ.get(ENV_ADMIN_URL_FILE) or DEFAULT_ADMIN_URL_FILE
    try:
        with open(path, encoding="utf-8") as secret_file:
            url_from_file = secret_file.read().strip()
    except (OSError, UnicodeDecodeError):
        return None
    return url_from_file or None


def get_public_host() -> str:
    return (os.environ.get(ENV_PUBLIC_HOST) or "").strip() or DEFAULT_PUBLIC_HOST


def get_public_port() -> int:
    """외부 포트 (숫자 아니면 기본 5432)"""
    try:
        return int(os.environ.get(ENV_PUBLIC_PORT) or DEFAULT_PUBLIC_PORT)
    except ValueError:
        return DEFAULT_PUBLIC_PORT
