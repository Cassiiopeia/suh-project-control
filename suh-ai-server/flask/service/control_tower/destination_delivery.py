"""관제소 프로젝트 받을 곳 발송: URL 암호화·표시 힌트·지원 확인, 프로젝트 알림 > 받을 곳마다 백그라운드 Apprise 발송 > 결과 코드 기록
URL 원문은 발송 직전 메모리에서만 사용 (저장·로그·결과 기록에 없음), Apprise는 처음 쓸 때 불러옴 (Flask 기동 비용 없음)"""
from __future__ import annotations

import logging
import os
import threading
from collections.abc import Mapping
from datetime import datetime
from functools import partial
from time import monotonic
from typing import Callable

from config.control_tower_config import CONTROL_TOWER_SECRET_ENV
from service.control_tower.alert_planner import GLOBAL_SCOPE, Notification
from service.control_tower.check_runner import utc_now
from service.control_tower.destination_store import Destination
from service.control_tower.event_dispatcher import to_channel_kind
from service.control_tower.log_text import sanitize_log_value
from service.control_tower.project_event_tokens import SECRET_MISSING_WARNING_INTERVAL_SECONDS
from service.secret_cipher import ENCRYPTION_SCHEME, SecretCipherError, decrypt_secret_text, encrypt_secret_text

logger = logging.getLogger(__name__)

# 암호화 키 파생 접두사: 접두사 + 비밀값 = PBKDF2 비밀 문구 (이벤트 토큰 해시 키와 분리)
DESTINATION_URL_KEY_PREFIX = "control-tower:destination-url:"
# 화면 힌트: 수단 + "://…" + 끝 4자리 (수단 뒤가 8자 미만이면 끝자리도 숨김)
URL_SCHEME_SEPARATOR = "://"
URL_HINT_ELLIPSIS = "…"
URL_HINT_SUFFIX_LENGTH = 4
URL_HINT_MIN_REMAINDER_LENGTH = 8
# Apprise 자체 로그 전부 차단 (CRITICAL보다 위): 플러그인 로그 일부가 URL 조각을 담음 > 결과는 우리 로그·결과 코드로만
APPRISE_LOGGER_NAME = "apprise"
APPRISE_SILENCED_LOG_LEVEL = logging.CRITICAL + 1
DELIVERY_THREAD_NAME = "control-tower-destination-deliver"
# 메시지 본문: 구획(본문 / 항목 줄들 / 링크) 사이 빈 줄, 항목 줄 형식
MESSAGE_SECTION_SEPARATOR = "\n\n"
FIELD_LINE_SEPARATOR = "\n"
FIELD_LINE_FORMAT = "{name}: {value}"
# last_result 코드 (예외 메시지는 URL을 담을 수 있어 형식 이름만)
RESULT_SENT = "sent"
RESULT_FAILED = "failed"
RESULT_SECRET_MISSING = "skipped:secret_missing"
RESULT_DECRYPT_FAILED = "skipped:decrypt_failed"
RESULT_ERROR_PREFIX = "error:"


class DestinationSecretNotConfiguredError(Exception):
    """CONTROL_TOWER_SECRET 없음 > 받을 곳 등록·수정 불가"""


def _read_url_key(environ: Mapping[str, str]) -> str | None:
    """비밀값 > 받을 곳 URL 암호화용 비밀 문구 (없으면 None)"""
    secret = environ.get(CONTROL_TOWER_SECRET_ENV)
    return DESTINATION_URL_KEY_PREFIX + secret if secret else None


def encrypt_destination_url(url: str, environ: Mapping[str, str] = os.environ) -> tuple[bytes, str]:
    """URL 원문 > (암호문, 암호화 방식)"""
    url_key = _read_url_key(environ)
    if url_key is None:
        raise DestinationSecretNotConfiguredError(CONTROL_TOWER_SECRET_ENV)
    return encrypt_secret_text(url, url_key), ENCRYPTION_SCHEME


def decrypt_destination_url(url_encrypted: bytes, encryption_scheme: str,
                            environ: Mapping[str, str] = os.environ) -> str:
    """암호문 > URL 원문 (비밀값 없음 DestinationSecretNotConfiguredError, 비밀값 변경·손상 SecretCipherError)"""
    url_key = _read_url_key(environ)
    if url_key is None:
        raise DestinationSecretNotConfiguredError(CONTROL_TOWER_SECRET_ENV)
    return decrypt_secret_text(url_encrypted, encryption_scheme, url_key)


def describe_url_hint(url: str) -> str:
    """URL > 화면 힌트 (discord://abc…xyz > discord://…wxyz, 짧으면 discord://…)"""
    scheme, separator, remainder = url.partition(URL_SCHEME_SEPARATOR)
    prefix = f"{scheme.lower()}{URL_SCHEME_SEPARATOR}" if separator else ""
    if not separator:
        remainder = url
    suffix = remainder[-URL_HINT_SUFFIX_LENGTH:] if len(remainder) >= URL_HINT_MIN_REMAINDER_LENGTH else ""
    return f"{prefix}{URL_HINT_ELLIPSIS}{suffix}"


def _load_apprise_module():
    """vendor.apprise 지연 로드 + Apprise 자체 로그 차단 (반복 호출 안전)"""
    logging.getLogger(APPRISE_LOGGER_NAME).setLevel(APPRISE_SILENCED_LOG_LEVEL)
    from vendor import apprise
    return apprise


def is_destination_url_supported(url: str) -> bool:
    """Apprise가 해석 가능한 URL인지 (빈 값·모르는 수단·형식 오류는 False)"""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        return _load_apprise_module().Apprise.instantiate(url) is not None
    except Exception:
        return False


def _send_with_apprise(url: str, title: str, body: str) -> bool:
    """URL 1개로 TEXT 형식 발송 > 성공 여부 (해석 실패도 False)"""
    apprise_module = _load_apprise_module()
    apprise_client = apprise_module.Apprise()
    if not apprise_client.add(url):
        return False
    # notify 결과 객체는 성공 시 참 (is True 비교 불가)
    return bool(apprise_client.notify(title=title, body=body, body_format=apprise_module.NotifyFormat.TEXT))


def build_destination_message(notification: Notification) -> tuple[str, str]:
    """알림 > (제목, 본문): 본문 > 빈 줄 > `이름: 값` 줄들 > 빈 줄 > 링크 (빈 구획 생략, 전부 비면 제목)"""
    field_lines = FIELD_LINE_SEPARATOR.join(
        FIELD_LINE_FORMAT.format(name=name, value=value) for name, value in notification.fields)
    sections = [section for section in (notification.body, field_lines, notification.link_url or "") if section]
    return notification.title, MESSAGE_SECTION_SEPARATOR.join(sections) or notification.title


class DestinationDeliverer:
    """프로젝트 알림 > 같은 (프로젝트, 채널 종류)의 사용 중 받을 곳: 받을 곳마다 백그라운드 발송, 재시도 없음"""

    def __init__(self, store, run_in_background: Callable[[Callable[[], None], str], None],
                 environ: Mapping[str, str] = os.environ, now_provider: Callable[[], datetime] = utc_now):
        self._store = store
        self._run_in_background = run_in_background
        self._environ = environ
        self._now_provider = now_provider
        self._secret_missing_warning_lock = threading.Lock()
        self._last_secret_missing_warning_monotonic: float | None = None

    def deliver(self, notification: Notification) -> None:
        """전역 알림 제외 > 받을 곳 조회 > 비밀값 확인(없으면 생략 기록) > 받을 곳마다 백그라운드 발송"""
        if notification.scope == GLOBAL_SCOPE:
            return
        destinations = self._store.list_enabled_destinations(notification.scope, to_channel_kind(notification))
        if not destinations:
            return
        url_key = _read_url_key(self._environ)
        if url_key is None:
            self._skip_for_missing_secret(notification, destinations)
            return
        title, body = build_destination_message(notification)
        for destination in destinations:
            self._run_in_background(partial(self._deliver_one, destination, url_key, title, body),
                                    DELIVERY_THREAD_NAME)

    def _deliver_one(self, destination: Destination, url_key: str, title: str, body: str) -> None:
        """복호화 > 발송 > 결과 기록 > 로그 (스레드 연결은 성공·실패 공통으로 닫음)"""
        try:
            result = _send_to_destination(destination, url_key, title, body)
            self._store.record_destination_result(destination.destination_id, result, self._now_provider())
            _log_result(destination, result)
        except Exception as error:
            logger.warning("[control-tower deliver] record failed : destination=%s %s",
                           destination.destination_id, type(error).__name__)
        finally:
            self._store.close_thread_connection()

    def _skip_for_missing_secret(self, notification: Notification, destinations: list[Destination]) -> None:
        """비밀값 없음: 받을 곳마다 생략 기록 + 경고 (간격 제한)"""
        now = self._now_provider()
        for destination in destinations:
            self._store.record_destination_result(destination.destination_id, RESULT_SECRET_MISSING, now)
        if self._should_warn_secret_missing():
            logger.warning("[control-tower deliver] skipped : %s not configured project=%s destinations=%d",
                           CONTROL_TOWER_SECRET_ENV, sanitize_log_value(notification.scope), len(destinations))

    def _should_warn_secret_missing(self) -> bool:
        """비밀값 없음 경고 허용 여부 (마지막 경고 후 최소 간격 경과, 스레드 안전)"""
        current_monotonic = monotonic()
        with self._secret_missing_warning_lock:
            last_monotonic = self._last_secret_missing_warning_monotonic
            elapsed_seconds = None if last_monotonic is None else current_monotonic - last_monotonic
            if elapsed_seconds is not None and elapsed_seconds < SECRET_MISSING_WARNING_INTERVAL_SECONDS:
                return False
            self._last_secret_missing_warning_monotonic = current_monotonic
            return True


def _send_to_destination(destination: Destination, url_key: str, title: str, body: str) -> str:
    """받을 곳 1개 발송 > 결과 코드 (URL 원문은 이 함수 밖으로 나가지 않음)"""
    try:
        url = decrypt_secret_text(destination.url_encrypted, destination.encryption_scheme, url_key)
    except SecretCipherError:
        return RESULT_DECRYPT_FAILED
    try:
        is_sent = _send_with_apprise(url, title, body)
    except Exception as error:
        return RESULT_ERROR_PREFIX + type(error).__name__
    return RESULT_SENT if is_sent else RESULT_FAILED


def _log_result(destination: Destination, result: str) -> None:
    """결과 코드 로그 (성공 info, 그 외 warning, URL·라벨 없음)"""
    if result == RESULT_SENT:
        logger.info("[control-tower deliver] sent : destination=%s project=%s kind=%s",
                    destination.destination_id, sanitize_log_value(destination.project_id),
                    sanitize_log_value(destination.kind))
        return
    logger.warning("[control-tower deliver] not delivered : destination=%s project=%s kind=%s result=%s",
                   destination.destination_id, sanitize_log_value(destination.project_id),
                   sanitize_log_value(destination.kind), result)
