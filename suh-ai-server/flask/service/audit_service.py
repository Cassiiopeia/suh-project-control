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
    TTS = "TTS"
    MODEL = "MODEL"
    SYSTEM = "SYSTEM"  # 향후 확장용


class AuditAction(str, Enum):
    SERVER_START = "SERVER_START"
    SERVER_STOP = "SERVER_STOP"
    SERVER_RESTART = "SERVER_RESTART"
    SETTINGS_UPDATE = "SETTINGS_UPDATE"
    BACKUP_CREATE = "BACKUP_CREATE"
    SERVER_UPDATE = "SERVER_UPDATE"
    TTS_INSTALL = "TTS_INSTALL"
    TTS_START = "TTS_START"
    TTS_STOP = "TTS_STOP"
    TTS_VOICE_ADD = "TTS_VOICE_ADD"
    TTS_VOICE_DELETE = "TTS_VOICE_DELETE"
    MODEL_DELETE = "MODEL_DELETE"
    MODEL_DOWNLOAD = "MODEL_DOWNLOAD"
    MODEL_DOWNLOAD_CANCEL = "MODEL_DOWNLOAD_CANCEL"
    BENCHMARK_CREATE = "BENCHMARK_CREATE"
    BENCHMARK_RESULT = "BENCHMARK_RESULT"
    SERVER_UPDATE_CHECK = "SERVER_UPDATE_CHECK"


def record(category: AuditCategory, action: AuditAction, actor_ip: str, detail: dict = None, *,
           client_ip: str = None, proxy_chain: list = None, user_agent: str = None,
           success: bool = True) -> bool:
    url = get_audit_database_url()
    if not url:
        return False
    # client_ip 미지정 호출(백그라운드 등)도 체인 첫 항목으로 실제 IP를 채운다
    if client_ip is None and actor_ip:
        client_ip = actor_ip.split(',')[0].strip()
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO audit_log (category, action, actor_ip, detail, "
                    "client_ip, proxy_chain, user_agent, success) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (category.value, action.value, actor_ip,
                     Json(detail) if detail is not None else None,
                     client_ip,
                     Json(proxy_chain) if proxy_chain else None,
                     user_agent, success),
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
                    "SELECT occurred_at, actor_ip, action, detail, category FROM audit_log "
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


def query_logs(category: str = None, action: str = None, success: bool = None,
               search: str = None, limit: int = 100, before_id: int = None) -> dict:
    """전용 감사로그 페이지용 구조화 조회 (최신순, 키셋 페이징)"""
    limit = min(max(int(limit), 1), MAX_LIST_LINES)
    url = get_audit_database_url()
    result = {
        'available': False,
        'location': _masked_location(url) if url else 'AUDIT_DATABASE_URL 미설정',
        'rows': [],
        'has_more': False,
    }
    if not url:
        return result
    where, params = [], []
    if category:
        where.append('category = %s')
        params.append(category)
    if action:
        where.append('action = %s')
        params.append(action)
    if success is not None:
        where.append('success = %s')
        params.append(success)
    if before_id is not None:
        where.append('id < %s')
        params.append(before_id)
    if search:
        like = f'%{search}%'
        where.append('(client_ip ILIKE %s OR actor_ip ILIKE %s OR action ILIKE %s '
                     'OR detail::text ILIKE %s)')
        params.extend([like, like, like, like])
    sql = ('SELECT id, occurred_at, category, action, actor_ip, client_ip, '
           'proxy_chain, user_agent, success, detail FROM audit_log')
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY id DESC LIMIT %s'
    params.append(limit + 1)  # 한 건 더 조회해 다음 페이지 유무 판정
    try:
        conn = psycopg2.connect(url, connect_timeout=3)
        try:
            with conn, conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        finally:
            conn.close()
        result['available'] = True
        result['has_more'] = len(rows) > limit
        for (row_id, occurred_at, cat, act, actor_ip, client_ip,
             proxy_chain, user_agent, ok, detail) in rows[:limit]:
            # 마이그레이션 전 기록은 client_ip가 비어 있으므로 체인 첫 항목으로 보정
            if not client_ip and actor_ip:
                client_ip = actor_ip.split(',')[0].strip()
            result['rows'].append({
                'id': row_id,
                'occurred_at': occurred_at.isoformat(),
                'category': cat,
                'action': act,
                'client_ip': client_ip,
                'proxy_chain': proxy_chain,
                'user_agent': user_agent,
                'success': ok,
                'detail': detail,
            })
        return result
    except Exception as e:
        logger.warning(f'Audit query failed: {e}')
        return result


def _format_line(occurred_at, actor_ip, action, detail, category=None) -> str:
    action_label = f'{category}/{action}' if category else action
    line = f'[{occurred_at.isoformat()}] {actor_ip} · {action_label}'
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
        # 대표 식별자 하나를 괄호로 노출 (보이스명, 엔진명, 항목 id 순)
        name = detail.get('name') or detail.get('engine') or detail.get('voice_id')
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
