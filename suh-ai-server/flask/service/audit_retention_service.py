"""
감사로그 보관 정리: 보관 기간(365일) 지난 audit_log 행 삭제, 하루 1회 백그라운드 실행
fail-open: DB 다운/URL 미설정이어도 서버 기동과 관리 기능을 막지 않는다.
"""
import logging
import threading
from typing import Optional

import psycopg2

from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)

# audit_log 보관 기간 (일) — 이 기간이 지난 행은 정리 때 삭제
AUDIT_LOG_RETENTION_DAYS = 365
# 정리 실행 간격 (24시간)
AUDIT_RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
# 기동 직후 DB 연결 경합을 피하려고 첫 정리를 미루는 시간 (5분)
AUDIT_RETENTION_FIRST_RUN_DELAY_SECONDS = 5 * 60


def purge_expired_audit_logs() -> Optional[int]:
    """보관 기간 지난 감사로그 삭제 > 삭제 행 수 (미설정·실패 시 None)"""
    url = get_audit_database_url()
    if not url:
        return None
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM audit_log WHERE occurred_at < now() - make_interval(days => %s)",
                    (AUDIT_LOG_RETENTION_DAYS,),
                )
                deleted_row_count = cur.rowcount
        finally:
            conn.close()
        logger.info(f'[audit retention] purged {deleted_row_count} rows older than {AUDIT_LOG_RETENTION_DAYS} days')
        return deleted_row_count
    except Exception as e:
        logger.warning(f'[audit retention] purge failed : {type(e).__name__}')
        return None


def run_retention_loop(stop_event: threading.Event,
                       interval_seconds: int = AUDIT_RETENTION_INTERVAL_SECONDS) -> None:
    """정리 반복: 대기 > 삭제 (예외는 기록만 하고 계속, stop_event 로 종료)"""
    while not stop_event.wait(interval_seconds):
        try:
            purge_expired_audit_logs()
        except Exception as e:
            logger.warning(f'[audit retention] loop error : {type(e).__name__}')


def start_audit_retention() -> threading.Thread:
    """데몬 스레드로 정리 시작 (첫 실행은 기동 5분 뒤, 이후 24시간마다)"""
    stop_event = threading.Event()

    def _run() -> None:
        if stop_event.wait(AUDIT_RETENTION_FIRST_RUN_DELAY_SECONDS):
            return
        try:
            purge_expired_audit_logs()
        except Exception as e:
            logger.warning(f'[audit retention] first run error : {type(e).__name__}')
        run_retention_loop(stop_event)

    thread = threading.Thread(target=_run, daemon=True, name='audit-retention')
    thread.start()
    return thread
