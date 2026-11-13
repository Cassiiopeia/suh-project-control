"""관제소 알림 허브 Python 클라이언트 (서버 전용, 의존성 없음)
모듈 함수 init/notify/notify_in_background는 기본 클라이언트 1개를 공유
"""
import threading
from typing import Optional

from .client import (DEFAULT_BASE_URL, DEFAULT_TIMEOUT_SECONDS, ERROR_CODE_NOT_INITIALIZED,
                     ControlTowerClient, FieldsInput)
from .result import NotifyResult

__all__ = ["ControlTowerClient", "NotifyResult", "init", "notify", "notify_in_background"]

_default_client: Optional[ControlTowerClient] = None
_default_client_lock = threading.Lock()


def init(*, project: str, token: str, base_url: str = DEFAULT_BASE_URL,
         timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> ControlTowerClient:
    """기본 클라이언트 설정 (다시 호출하면 교체, 설정이 잘못되면 ValueError)"""
    global _default_client
    client = ControlTowerClient(project=project, token=token, base_url=base_url,
                                timeout_seconds=timeout_seconds)
    with _default_client_lock:
        _default_client = client
    return client


def _reset_for_test() -> None:
    """기본 클라이언트 해제 (테스트 전용)"""
    global _default_client
    with _default_client_lock:
        _default_client = None


def notify(kind: str, title: str, fields: Optional[FieldsInput] = None, body: Optional[str] = None,
           url: Optional[str] = None, severity: str = "info",
           dedupe_key: Optional[str] = None) -> NotifyResult:
    """기본 클라이언트로 전송 (init 전이면 not_initialized 결과)"""
    client = _default_client
    if client is None:
        return NotifyResult(is_accepted=False, error_code=ERROR_CODE_NOT_INITIALIZED)
    return client.notify(kind, title, fields, body, url, severity, dedupe_key)


def notify_in_background(kind: str, title: str, fields: Optional[FieldsInput] = None,
                         body: Optional[str] = None, url: Optional[str] = None, severity: str = "info",
                         dedupe_key: Optional[str] = None) -> Optional[threading.Thread]:
    """기본 클라이언트로 백그라운드 전송 (init 전이면 None)"""
    client = _default_client
    if client is None:
        return None
    return client.notify_in_background(kind, title, fields, body, url, severity, dedupe_key)
