"""
감사로그 DB 설정 + 마이그레이션
AUDIT_DATABASE_URL 미설정/DB 다운은 앱 기동을 막지 않는다 (fail-open)
"""
import logging
import os

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# flask/.env (gitignore 대상, CICD가 서버에 생성)
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'migrations'))


def get_audit_database_url():
    return os.environ.get('AUDIT_DATABASE_URL') or None


def apply_migrations() -> bool:
    """yoyo 마이그레이션 적용 (Flyway처럼 앱 기동 시 자동). 실패해도 앱은 기동한다."""
    url = get_audit_database_url()
    if not url:
        logger.warning('AUDIT_DATABASE_URL not set - audit migrations skipped')
        return False
    try:
        from yoyo import get_backend, read_migrations
        backend = get_backend(url)
        migrations = read_migrations(MIGRATIONS_DIR)
        with backend.lock():
            backend.apply_migrations(backend.to_apply(migrations))
        logger.info('Audit DB migrations applied')
        return True
    except Exception as e:
        logger.warning(f'Audit DB migration skipped (will retry on next start): {e}')
        return False
