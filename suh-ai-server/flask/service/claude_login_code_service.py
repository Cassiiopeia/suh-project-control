"""
Claude 로그인 6자리 코드 작업: 메일 대기 > 수신 > 링크 열기 > 코드 발급
작업은 동시에 1개, 상태는 메모리 보관 (status API 폴링), 코드는 메일 수신 10분 후 숨김
"""
import logging
import os
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone

from config import claude_login_config as config
from service import audit_service
from service.audit_service import AuditAction, AuditCategory
from service.claude_login_browser_client import (
    BrowserClientError, LoginCodeNotFoundError, read_login_code)
from service.claude_login_mail_client import MailClientError, find_new_magic_link_mail

logger = logging.getLogger(__name__)

# 실패 화면 캡처: logs/claude_login_failure.png
SCREENSHOT_PATH = os.path.join(os.path.dirname(__file__), '..', 'logs', 'claude_login_failure.png')
# 처리한 메일 Message-ID 보관 개수 (1회용 링크 재사용 방지)
PROCESSED_MESSAGE_ID_LIMIT = 50

_lock = threading.Lock()
_state = {}
_processed_message_ids = deque(maxlen=PROCESSED_MESSAGE_ID_LIMIT)
# (job_id, client_ip): 코드를 이미 받아 간 클라이언트
_viewed_clients = set()


class NotConfiguredError(Exception):
    """Gmail 주소·앱 비밀번호 환경변수 미설정"""


def _now():
    return datetime.now(timezone.utc)


def _sleep(seconds):
    time.sleep(seconds)


def _reset_for_test():
    with _lock:
        _state.clear()
        _processed_message_ids.clear()
        _viewed_clients.clear()


def start_request(trigger: str, client: dict, *, run_in_thread=True):
    """대기 시작 > (상태, 새 작업 여부). 진행 중이면 기존 작업 상태 반환"""
    if not config.is_configured():
        raise NotConfiguredError('gmail address or app password not set')
    with _lock:
        if _state.get('status') == 'running':
            return _snapshot(_now()), False
        started_at = _now()
        job_id = uuid.uuid4().hex[:12]
        _state.clear()
        _state.update({
            'job_id': job_id, 'status': 'running', 'step': 'waiting', 'trigger': trigger,
            'started_at': started_at, 'step_times': {'waiting': started_at},
            'mail_received_at': None, 'expires_at': None, 'code': None,
            'failure_reason': None, 'has_screenshot': False,
        })
        state = _snapshot(started_at)
    logger.info('[claude login] job started : job=%s trigger=%s', job_id, trigger)
    if run_in_thread:
        threading.Thread(target=_run_job, args=(job_id, client), daemon=True).start()
    else:
        _run_job(job_id, client)
    return state, True


def get_state(now: datetime = None) -> dict:
    """현재 작업 상태 (유효시간 지난 코드는 숨기고 expired 처리)"""
    with _lock:
        return _snapshot(now or _now())


def should_record_view(job_id: str, client_ip: str) -> bool:
    """작업·클라이언트별 첫 코드 열람만 True"""
    with _lock:
        key = (job_id, client_ip)
        if key in _viewed_clients:
            return False
        _viewed_clients.add(key)
        return True


def _run_job(job_id: str, client: dict):
    """메일 대기 > 링크 열기 > 코드 저장 (실패 단계·사유 기록, 감사 1회)"""
    started_at = _state['started_at']
    deadline = started_at + timedelta(seconds=config.MAIL_WAIT_TIMEOUT_SECONDS)
    accept_after = started_at - timedelta(seconds=config.MAIL_ACCEPT_BEFORE_START_SECONDS)
    address = config.get_gmail_address()
    try:
        # 메일 대기 (5초 간격, 최대 10분)
        mail = None
        while _now() < deadline:
            mail = find_new_magic_link_mail(address, config.get_gmail_app_password(),
                                            accept_after, set(_processed_message_ids))
            if mail:
                break
            _sleep(config.POLL_INTERVAL_SECONDS)
        if mail is None:
            _finish(job_id, client, failure_reason='timeout')
            return
        # 수신 > 링크 열기 (1회용이라 결과와 무관하게 처리 목록에 추가)
        _processed_message_ids.append(mail.message_id)
        _set_step(job_id, 'received', mail_received_at=mail.received_at)
        _set_step(job_id, 'opening')
        login_code = read_login_code(mail.magic_link, SCREENSHOT_PATH)
        _finish(job_id, client, code=login_code)
    except MailClientError as error:
        logger.warning('[claude login] mail failed : job=%s %s', job_id, error)
        _finish(job_id, client, failure_reason='mail_error')
    except LoginCodeNotFoundError:
        _finish(job_id, client, failure_reason='code_not_found', has_screenshot=True)
    except BrowserClientError as error:
        logger.warning('[claude login] browser failed : job=%s %s', job_id, error)
        _finish(job_id, client, failure_reason='browser_error')
    except Exception:  # 스레드가 조용히 죽지 않도록 (상태는 failed 로 남김)
        logger.exception('[claude login] unexpected failure : job=%s', job_id)
        _finish(job_id, client, failure_reason='browser_error')


def _set_step(job_id: str, step: str, **fields):
    with _lock:
        if _state.get('job_id') != job_id:
            return
        _state['step'] = step
        _state['step_times'][step] = _now()
        _state.update(fields)


def _finish(job_id: str, client: dict, *, code=None, failure_reason=None, has_screenshot=False):
    """작업 종료 > 상태 확정 + 감사 CLAUDE_CODE_ISSUED (코드 원문 제외)"""
    finished_at = _now()
    is_success = code is not None
    with _lock:
        if _state.get('job_id') != job_id:
            return
        mail_received_at = _state.get('mail_received_at')
        _state.update({'status': 'issued' if is_success else 'failed',
                       'code': code, 'failure_reason': failure_reason,
                       'has_screenshot': has_screenshot})
        if is_success:
            _state['step'] = 'issued'
            _state['step_times']['issued'] = finished_at
            _state['expires_at'] = mail_received_at + timedelta(seconds=config.MAGIC_LINK_VALID_SECONDS)
        started_at = _state['started_at']
    logger.info('[claude login] job finished : job=%s result=%s', job_id,
                'issued' if is_success else failure_reason)
    audit_service.record(
        AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_CODE_ISSUED, client.get('actor_ip'),
        {'job_id': job_id, 'failure_reason': failure_reason,
         'mail_received_at': mail_received_at.isoformat() if mail_received_at else None,
         'elapsed_seconds': round((finished_at - started_at).total_seconds(), 1),
         'account': config.get_gmail_address()},
        client_ip=client.get('client_ip'), proxy_chain=client.get('proxy_chain'),
        user_agent=client.get('user_agent'), success=is_success)


def _snapshot(now: datetime) -> dict:
    """내부 상태 > API 응답 형태 (datetime > ISO, 만료 처리)"""
    if not _state:
        return {'job_id': None, 'status': 'idle', 'is_configured': config.is_configured(),
                'account': config.get_gmail_address()}
    expires_at = _state.get('expires_at')
    if _state['status'] == 'issued' and expires_at and now >= expires_at:
        _state['status'] = 'expired'
        _state['code'] = None

    def to_iso(value):
        return value.isoformat() if value else None
    return {
        'job_id': _state['job_id'], 'status': _state['status'], 'step': _state['step'],
        'trigger': _state['trigger'], 'started_at': to_iso(_state['started_at']),
        'step_times': {step: to_iso(at) for step, at in _state['step_times'].items()},
        'mail_received_at': to_iso(_state['mail_received_at']), 'expires_at': to_iso(expires_at),
        'code': _state['code'], 'failure_reason': _state['failure_reason'],
        'has_screenshot': _state['has_screenshot'], 'account': config.get_gmail_address(),
        'is_configured': config.is_configured(),
    }
