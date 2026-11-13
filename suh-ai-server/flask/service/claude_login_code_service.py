"""
Claude 로그인 6자리 코드 작업: 계정별 메일 대기 > 수신 > 링크 열기 > 코드 발급
작업은 계정당 1개(계정 간 동시), 상태는 메모리 보관 (status API 폴링), 코드는 메일 수신 10분 후 숨김
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
from service import claude_login_account_repository as account_repository
from service import claude_login_account_service as account_service
from service.audit_service import AuditAction, AuditCategory
from service.claude_login_browser_client import (
    BrowserClientError, LoginCodeNotFoundError, read_login_code)
from service.claude_login_mail_client import MailClientError, find_new_magic_link_mail
from service.secret_cipher import SecretCipherError
from service.claude_login_event_notifier import notify_claude_code_event

logger = logging.getLogger(__name__)

# 실패 화면 캡처: logs/claude_login_failure_{계정 id}.png
SCREENSHOT_DIRECTORY = os.path.join(os.path.dirname(__file__), '..', 'logs')
# 처리한 메일 Message-ID 보관 개수 (계정별, 1회용 링크 재사용 방지)
PROCESSED_MESSAGE_ID_LIMIT = 50

_lock = threading.Lock()
# account_id > 작업 상태
_states = {}
# account_id > 처리한 Message-ID
_processed_message_ids_by_account = {}
# (job_id, client_ip): 코드를 이미 받아 간 클라이언트
_viewed_clients = set()


def _now():
    return datetime.now(timezone.utc)


def _sleep(seconds):
    time.sleep(seconds)


def _reset_for_test():
    with _lock:
        _states.clear()
        _processed_message_ids_by_account.clear()
        _viewed_clients.clear()


def screenshot_path(account_id: int) -> str:
    return os.path.join(SCREENSHOT_DIRECTORY, f'claude_login_failure_{int(account_id)}.png')


def start_requests(trigger: str, client: dict, account_id: int = None, *, run_in_thread=True) -> list:
    """대기 시작 (account_id 없으면 사용 중 계정 전체) > [(상태, 새 작업 여부)]
    예외: SecretNotConfiguredError, AccountStoreUnavailableError, AccountNotFoundError"""
    accounts = _load_target_accounts(account_id)
    return [_start_account_job(account, trigger, client, run_in_thread) for account in accounts]


def get_states(now: datetime = None) -> list:
    """사용 중 계정 + 진행 기록 있는 계정의 상태 목록 (유효시간 지난 코드는 숨김)"""
    accounts = account_repository.list_accounts()
    now = now or _now()
    with _lock:
        return [_snapshot(account, now) for account in accounts
                if account.is_enabled or account.id in _states]


def get_state(account_id: int, now: datetime = None):
    """계정 1개 상태 (기록 없으면 None)"""
    with _lock:
        state = _states.get(account_id)
        if state is None:
            return None
        _expire_if_needed(state, now or _now())
        return _to_response(state)


def should_record_view(job_id: str, client_ip: str) -> bool:
    """작업·클라이언트별 첫 코드 열람만 True"""
    with _lock:
        key = (job_id, client_ip)
        if key in _viewed_clients:
            return False
        _viewed_clients.add(key)
        return True


def _load_target_accounts(account_id):
    """대상 계정 조회 (단건 지정 시 사용 중지 계정도 허용)"""
    if account_id is None:
        return account_repository.list_accounts(is_enabled_only=True)
    account = account_repository.find_account(account_id)
    if account is None:
        raise account_service.AccountNotFoundError(account_id)
    return [account]


def _start_account_job(account, trigger: str, client: dict, run_in_thread: bool):
    """계정 1개 작업 시작 (진행 중·유효 코드 있으면 유지) > (상태, 새 작업 여부)"""
    with _lock:
        current = _states.get(account.id)
        if current:
            _expire_if_needed(current, _now())
            # 진행 중이거나, 화면 재진입(auto)인데 유효한 코드가 있으면 기존 작업 유지
            if current['status'] == 'running' or (trigger == 'auto' and current['status'] == 'issued'):
                return _to_response(current), False
        started_at = _now()
        job_id = uuid.uuid4().hex[:12]
        _states[account.id] = {
            'account_id': account.id, 'display_name': account.display_name,
            'gmail_address': account.gmail_address,
            'job_id': job_id, 'status': 'running', 'step': 'waiting', 'trigger': trigger,
            'started_at': started_at, 'step_times': {'waiting': started_at},
            'mail_received_at': None, 'expires_at': None, 'code': None,
            'failure_reason': None, 'has_screenshot': False,
        }
        state = _to_response(_states[account.id])
    logger.info('[claude login] job started : account=%s job=%s trigger=%s', account.id, job_id, trigger)
    if run_in_thread:
        threading.Thread(target=_run_job, args=(account, job_id, client), daemon=True).start()
    else:
        _run_job(account, job_id, client)
    return state, True


def _run_job(account, job_id: str, client: dict):
    """복호화 > 메일 대기 > 링크 열기 > 코드 저장 (실패 단계·사유 기록, 감사 1회)"""
    with _lock:
        started_at = _states[account.id]['started_at']
    deadline = started_at + timedelta(seconds=config.MAIL_WAIT_TIMEOUT_SECONDS)
    accept_after = started_at - timedelta(seconds=config.MAIL_ACCEPT_BEFORE_START_SECONDS)
    try:
        credential = account_service.load_credential(account)
        mail = _wait_for_mail(account.id, job_id, credential, accept_after, deadline)
        if mail is None:
            _finish(account, job_id, client, failure_reason='timeout')
            return
        # 수신 > 링크 열기 (1회용이라 결과와 무관하게 처리 목록에 추가)
        _processed_ids(account.id).append(mail.message_id)
        _set_step(account.id, job_id, 'received', mail_received_at=mail.received_at)
        _set_step(account.id, job_id, 'opening')
        login_code = read_login_code(mail.magic_link, screenshot_path(account.id))
        _finish(account, job_id, client, code=login_code)
    except (SecretCipherError, account_service.SecretNotConfiguredError) as error:
        logger.warning('[claude login] decrypt failed : account=%s job=%s %s', account.id, job_id, error)
        _finish(account, job_id, client, failure_reason='decrypt_error')
    except MailClientError as error:
        logger.warning('[claude login] mail failed : account=%s job=%s %s', account.id, job_id, error)
        _finish(account, job_id, client, failure_reason='mail_error')
    except LoginCodeNotFoundError:
        _finish(account, job_id, client, failure_reason='code_not_found', has_screenshot=True)
    except BrowserClientError as error:
        logger.warning('[claude login] browser failed : account=%s job=%s %s', account.id, job_id, error)
        _finish(account, job_id, client, failure_reason='browser_error')
    except Exception:  # 스레드가 조용히 죽지 않도록 (상태는 failed 로 남김)
        logger.exception('[claude login] unexpected failure : account=%s job=%s', account.id, job_id)
        _finish(account, job_id, client, failure_reason='browser_error')


def _wait_for_mail(account_id: int, job_id: str, credential, accept_after: datetime, deadline: datetime):
    """5초 간격 메일 확인 (최대 10분, 다른 작업으로 교체되면 중단) > 메일 또는 None"""
    while _now() < deadline and _is_current_job(account_id, job_id):
        mail = find_new_magic_link_mail(credential.gmail_address, credential.app_password,
                                        accept_after, set(_processed_ids(account_id)))
        if mail:
            return mail
        _sleep(config.POLL_INTERVAL_SECONDS)
    return None


def _is_current_job(account_id: int, job_id: str) -> bool:
    with _lock:
        state = _states.get(account_id)
        return bool(state) and state['job_id'] == job_id


def _processed_ids(account_id: int) -> deque:
    with _lock:
        return _processed_message_ids_by_account.setdefault(
            account_id, deque(maxlen=PROCESSED_MESSAGE_ID_LIMIT))


def _set_step(account_id: int, job_id: str, step: str, **fields):
    with _lock:
        state = _states.get(account_id)
        if not state or state['job_id'] != job_id:
            return
        state['step'] = step
        state['step_times'][step] = _now()
        state.update(fields)


def _finish(account, job_id: str, client: dict, *, code=None, failure_reason=None, has_screenshot=False):
    """작업 종료 > 상태 확정 + 성공 시각 기록 + 감사 CLAUDE_CODE_ISSUED (코드 원문 제외)"""
    finished_at = _now()
    is_success = code is not None
    with _lock:
        state = _states.get(account.id)
        if not state or state['job_id'] != job_id:
            return
        mail_received_at = state.get('mail_received_at')
        state.update({'status': 'issued' if is_success else 'failed', 'code': code,
                      'failure_reason': failure_reason, 'has_screenshot': has_screenshot})
        if is_success:
            state['step'] = 'issued'
            state['step_times']['issued'] = finished_at
            state['expires_at'] = mail_received_at + timedelta(seconds=config.MAGIC_LINK_VALID_SECONDS)
        started_at = state['started_at']
    logger.info('[claude login] job finished : account=%s job=%s result=%s', account.id, job_id,
                'issued' if is_success else failure_reason)
    if is_success:
        account_repository.mark_success(account.id)
    audit_service.record(
        AuditCategory.CLAUDE_LOGIN, AuditAction.CLAUDE_CODE_ISSUED, client.get('actor_ip'),
        {'job_id': job_id, 'account_id': account.id, 'account': account.gmail_address,
         'failure_reason': failure_reason,
         'mail_received_at': mail_received_at.isoformat() if mail_received_at else None,
         'elapsed_seconds': round((finished_at - started_at).total_seconds(), 1)},
        client_ip=client.get('client_ip'), proxy_chain=client.get('proxy_chain'),
        user_agent=client.get('user_agent'), success=is_success)
    # 발급 알림 (성공만, 코드·Gmail 주소 제외)
    if is_success:
        notify_claude_code_event(
            'Claude 코드 발급', f'claude-code:issued:{job_id}', account.display_name,
            client.get('client_ip'), client.get('user_agent'))


def _snapshot(account, now: datetime) -> dict:
    """계정 + 작업 상태 > 응답 (작업 기록 없으면 idle)"""
    state = _states.get(account.id)
    if state is None:
        return {'account_id': account.id, 'display_name': account.display_name,
                'gmail_address': account.gmail_address, 'is_enabled': account.is_enabled,
                'job_id': None, 'status': 'idle', 'step': None, 'step_times': {}, 'code': None,
                'mail_received_at': None, 'expires_at': None, 'failure_reason': None,
                'has_screenshot': False, 'started_at': None, 'trigger': None}
    _expire_if_needed(state, now)
    # 화면에는 최신 계정 이름·사용 여부 표시
    state['display_name'] = account.display_name
    return {**_to_response(state), 'is_enabled': account.is_enabled}


def _expire_if_needed(state: dict, now: datetime):
    """유효시간 지난 코드 > expired + 코드 삭제 (_lock 안에서 호출)"""
    expires_at = state.get('expires_at')
    if state['status'] == 'issued' and expires_at and now >= expires_at:
        state['status'] = 'expired'
        state['code'] = None


def _to_response(state: dict) -> dict:
    """내부 상태 > API 응답 형태 (datetime > ISO)"""
    def to_iso(value):
        return value.isoformat() if value else None
    return {
        'account_id': state['account_id'], 'display_name': state['display_name'],
        'gmail_address': state['gmail_address'],
        'job_id': state['job_id'], 'status': state['status'], 'step': state['step'],
        'trigger': state['trigger'], 'started_at': to_iso(state['started_at']),
        'step_times': {step: to_iso(at) for step, at in state['step_times'].items()},
        'mail_received_at': to_iso(state['mail_received_at']), 'expires_at': to_iso(state['expires_at']),
        'code': state['code'], 'failure_reason': state['failure_reason'],
        'has_screenshot': state['has_screenshot'],
    }
