"""
관리 행위 감사 공통 데코레이터

규칙 (에이전트/개발자 공통 — flask/CLAUDE.md 참고):
- 상태를 변경하는 관리 엔드포인트(POST/PUT/DELETE)에는 반드시 @audited를 부착한다.
- 응답 status < 400 이면 success=True, 그 외/예외는 success=False로 자동 기록된다.
- 동적 값은 핸들러 안에서 set_audit_action()/set_audit_detail()로 지정한다.
- 감사 대상이 아닌 요청(검증 실패 등)은 action 미지정 또는 skip_audit()로 생략된다.
- 요청 컨텍스트 밖(백그라운드 스레드)은 audit_service.record()를 직접 호출한다.
"""
import logging
from functools import wraps

from flask import g, request

from service import audit_service
from service.audit_service import AuditAction, AuditCategory

logger = logging.getLogger(__name__)


def client_info() -> dict:
    """XFF 체인 분해: 첫 항목=실제 클라이언트, 나머지=경유 프록시"""
    forwarded = request.headers.get('X-Forwarded-For', '')
    hops = [h.strip() for h in forwarded.split(',') if h.strip()]
    fallback = request.remote_addr or 'unknown'
    return {
        'actor_ip': forwarded if hops else fallback,  # 하위호환용 원문 체인
        'client_ip': hops[0] if hops else fallback,
        'proxy_chain': hops[1:],
        'user_agent': request.headers.get('User-Agent'),
    }


def set_audit_action(action: AuditAction):
    g.audit_action = action


def set_audit_detail(detail: dict):
    merged = getattr(g, 'audit_detail', None) or {}
    merged.update(detail)
    g.audit_detail = merged


def skip_audit():
    g.audit_skip = True


def audited(category: AuditCategory, action: AuditAction = None):
    """상태 변경 라우트용 감사 데코레이터. action=None이면 set_audit_action() 필수."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                resp = fn(*args, **kwargs)
            except Exception as e:
                _record(category, action, success=False, error=str(e))
                raise  # 감사 기록 후 기존 에러 흐름 유지
            status = _status_of(resp)
            _record(category, action, success=status < 400)
            return resp
        return wrapper
    return decorator


def _status_of(resp) -> int:
    """Flask 뷰 반환값(Response 또는 (body, status) 튜플)에서 status 추출"""
    if isinstance(resp, tuple) and len(resp) >= 2 and isinstance(resp[1], int):
        return resp[1]
    return getattr(resp, 'status_code', 200)


def _record(category, default_action, success, error=None):
    try:
        if getattr(g, 'audit_skip', False):
            return
        resolved = getattr(g, 'audit_action', None) or default_action
        if resolved is None:
            return  # 검증 실패 등 감사 대상 아님
        detail = getattr(g, 'audit_detail', None)
        if error:
            detail = {**(detail or {}), 'error': error}
        info = client_info()
        audit_service.record(
            category, resolved, info['actor_ip'], detail,
            client_ip=info['client_ip'], proxy_chain=info['proxy_chain'],
            user_agent=info['user_agent'], success=success,
        )
    except Exception as e:
        # 감사 실패가 원 요청을 깨지 않게 격리 (fail-open)
        logger.warning(f'Audit decorator record failed: {e}')
