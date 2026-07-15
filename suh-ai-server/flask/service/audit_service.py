"""
관리 행위 감사로그 (PostgreSQL)
fail-open: DB 다운/URL 미설정이 관리 행위를 절대 막지 않는다.
category/action은 코드 enum + DB VARCHAR — 새 값 추가 시 마이그레이션 불필요.
"""
import logging
from enum import Enum
from urllib.parse import urlsplit

import psycopg2
from psycopg2.extras import Json

from config.db_config import get_audit_database_url

logger = logging.getLogger(__name__)

MAX_LIST_LINES = 500


class AuditCategory(str, Enum):
    PALWORLD = "PALWORLD"
    SYSTEM = "SYSTEM"  # 향후 확장용


class AuditAction(str, Enum):
    SERVER_START = "SERVER_START"
    SERVER_STOP = "SERVER_STOP"
    SERVER_RESTART = "SERVER_RESTART"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    BACKUP_CREATE = "BACKUP_CREATE"


def record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict = None) -> bool:
    url = get_audit_database_url()
    if not url:
        return False
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (category, action, actor_ip, detail) VALUES (%s, %s, %s, %s)",
                    (category.value, action.value, actor_ip,
                     Json(detail) if detail is not None else None),
                )
        finally:
            conn.close()
        return True
    except Exception as e:
        logger.warning(f'Audit record failed ({action}): {e}')
        return False


def list_logs(lines: int = 200) -> dict:
    """로그 뷰어 응답 형태로 최근 감사로그 반환 (오래된 것 → 최신 순)"""
    lines = min(int(lines), MAX_LIST_LINES)
    url = get_audit_database_url()
    result = {
        'source': 'audit',
        'log_file': _masked_location(url) if url else 'AUDIT_DATABASE_URL 미설정',
        'exists': False,
        'size_bytes': 0,
        'logs': [],
    }
    if not url:
        return result
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "SELECT occurred_at, actor_ip, action, detail FROM audit_log "
                    "ORDER BY occurred_at DESC, id DESC LIMIT %s",
                    (lines,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        result['exists'] = True
        result['logs'] = [_format_line(*row) for row in reversed(rows)]
        return result
    except Exception as e:
        logger.warning(f'Audit list failed: {e}')
        return result


def _format_line(occurred_at, actor_ip, action, detail) -> str:
    line = f'[{occurred_at.isoformat()}] {actor_ip} · {action}'
    if detail and isinstance(detail, dict):
        changed = detail.get('changed')
        if changed and isinstance(changed, dict):
            parts = []
            for key, value in changed.items():
                if isinstance(value, dict):
                    parts.append(f'{key}: {value.get("from")} → {value.get("to")}')
                else:
                    parts.append(f'{key}: {value}')
            return f'{line} ({", ".join(parts)})'
        name = detail.get('name')
        if name:
            return f'{line} ({name})'
    return line


def _masked_location(url: str) -> str:
    """자격증명을 제거한 DB 위치 (뷰어의 파일 경로 자리에 표시)"""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        port = f':{parts.port}' if parts.port else ''
        return f'{parts.scheme}://{host}{port}{parts.path}'
    except Exception:
        return 'postgresql://(masked)'
