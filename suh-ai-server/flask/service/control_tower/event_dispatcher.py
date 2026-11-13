"""관제소 알림 발송 단일 지점: 플래너 알림·앱 이벤트 > 바인딩 채널 > 디스코드 임베드
이벤트 입구는 검증 > 중복 억제 > 발송 순서, 플래너 알림은 중복 억제 없이 바로 발송
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from service.control_tower.alert_planner import GLOBAL_SCOPE, INFRASTRUCTURE_KIND, Notification
from service.control_tower.discord_messages import to_embed
from service.control_tower.registry_models import EVENT_KIND_INFO, EVENT_KINDS  # noqa: F401 (EVENT_KINDS 재노출, 허용 목록 단일 원본)

logger = logging.getLogger(__name__)

# 이벤트 severity 허용 목록
EVENT_SEVERITIES = ("info", "warning", "critical")
# info 이벤트는 프로젝트 상태 채널로
INFO_EVENT_KIND = EVENT_KIND_INFO
STATUS_CHANNEL_KIND = "status"
# 이벤트 제목 길이 범위 (글자 수)
TITLE_MIN_LENGTH = 1
TITLE_MAX_LENGTH = 200
# 이벤트 본문 최대 길이 (글자 수)
BODY_MAX_LENGTH = 2000
# 이벤트 링크는 https만 허용
ALLOWED_URL_PREFIX = "https://"
# 이벤트 링크 최대 길이 (글자 수, 디스코드 임베드 url 상한)
URL_MAX_LENGTH = 2048
# 이벤트 fields: 최대 개수, 이름 길이, 값 길이 (글자 수, 디스코드 임베드 field 상한 이내)
EVENT_FIELDS_MAX_COUNT = 10
EVENT_FIELD_NAME_MAX_LENGTH = 40
EVENT_FIELD_VALUE_MAX_LENGTH = 200
# 거부 응답에 싣는 kind 최대 길이 (글자 수)
UNKNOWN_KIND_ECHO_MAX_LENGTH = 50
HTTP_ACCEPTED = 202
HTTP_BAD_REQUEST = 400


class EventDispatcher:
    def __init__(self, registry_provider: Callable, store, discord_client_provider: Callable,
                 status_page_url: str):
        self._registry_provider = registry_provider
        self._store = store
        self._discord_client_provider = discord_client_provider
        self._status_page_url = status_page_url

    def is_delivery_configured(self) -> bool:
        """디스코드 클라이언트 설정 여부 (미설정이면 발송 실패를 재시도하지 않음)"""
        return self._discord_client_provider() is not None

    def dispatch(self, notification: Notification) -> bool:
        """알림 1건 발송: 클라이언트 확인 > 채널 선택(없으면 global alert) > 임베드 전송"""
        discord_client = self._discord_client_provider()
        if discord_client is None:
            logger.warning("[control-tower dispatch] skipped : discord client is not configured")
            return False
        channel_id = self._find_channel_id(notification)
        if channel_id is None:
            return False
        return discord_client.send_embed(channel_id, to_embed(notification, self._status_page_url))

    def allowed_event_kinds(self, project_id: str) -> frozenset[str]:
        """프로젝트가 받는 이벤트 종류: 기본 종류 + 사용자 정의 종류 (모르는 프로젝트는 기본만)"""
        project = next((spec for spec in self._registry_provider().projects if spec.id == project_id), None)
        custom_kinds = {kind_spec.kind for kind_spec in project.event_kinds} if project else set()
        return frozenset(EVENT_KINDS) | custom_kinds

    def accept_event(self, project_id: str, payload: dict, now: datetime) -> tuple[int, dict]:
        """앱 이벤트 접수: 종류 확인 > 검증 > 중복 억제 기록 > 발송 (발송 실패해도 접수 응답)"""
        # 종류 확인 (모르는 종류는 기록·발송 없이 거부)
        allowed_kinds = self.allowed_event_kinds(project_id)
        received_kind = payload.get("kind")
        if isinstance(received_kind, str) and received_kind not in allowed_kinds:
            logger.warning("[control-tower event] unknown kind : project %s kind %s",
                           _sanitize_log_value(project_id), _sanitize_log_value(received_kind))
            return HTTP_BAD_REQUEST, {"error": "unknown_kind",
                                      "kind": received_kind[:UNKNOWN_KIND_ECHO_MAX_LENGTH]}

        invalid_fields = validate_event_payload(payload, allowed_kinds)
        if invalid_fields:
            return HTTP_BAD_REQUEST, {"error": "invalid", "fields": invalid_fields}

        dedupe_key = payload.get("dedupe_key") or ""
        if not self._store.record_event(project_id, payload["kind"], dedupe_key, now):
            return HTTP_ACCEPTED, {"accepted": True, "deduplicated": True}

        notification = Notification(
            scope=project_id, kind=payload["kind"], severity=payload["severity"], title=payload["title"],
            body=payload.get("body") or "", service_ids=(), dedupe_key=dedupe_key, link_url=payload.get("url"),
            fields=tuple((field["name"], field["value"]) for field in payload.get("fields") or ()))
        if not self.dispatch(notification):
            logger.warning("[control-tower dispatch] event accepted but not delivered : project %s kind %s",
                           _sanitize_log_value(project_id), notification.kind)
        return HTTP_ACCEPTED, {"accepted": True, "deduplicated": False}

    def _find_channel_id(self, notification: Notification) -> str | None:
        """(scope, 채널 종류) 바인딩 > 없으면 (global, alert) 대체 + 경고, 둘 다 없으면 None"""
        channel_kind = STATUS_CHANNEL_KIND if notification.kind == INFO_EVENT_KIND else notification.kind
        channel_id = self._store.get_binding(notification.scope, channel_kind)
        if channel_id is not None:
            return channel_id
        logger.warning("[control-tower dispatch] binding missing : scope %s kind %s > fallback global alert",
                       _sanitize_log_value(notification.scope), channel_kind)
        channel_id = self._store.get_binding(GLOBAL_SCOPE, INFRASTRUCTURE_KIND)
        if channel_id is None:
            logger.warning("[control-tower dispatch] dropped : global alert binding missing")
        return channel_id


def validate_event_payload(payload: dict, allowed_kinds: frozenset[str]) -> list[str]:
    """이벤트 필드 검증: 잘못된 필드 이름 목록 (kind, severity, title, body, fields, dedupe_key, url 순)"""
    invalid_fields: list[str] = []
    if payload.get("kind") not in allowed_kinds:
        invalid_fields.append("kind")
    if payload.get("severity") not in EVENT_SEVERITIES:
        invalid_fields.append("severity")
    title = payload.get("title")
    if not isinstance(title, str) or not TITLE_MIN_LENGTH <= len(title) <= TITLE_MAX_LENGTH:
        invalid_fields.append("title")
    body = payload.get("body")
    if body is not None and (not isinstance(body, str) or len(body) > BODY_MAX_LENGTH):
        invalid_fields.append("body")
    event_fields = payload.get("fields")
    if event_fields is not None and not _is_valid_event_fields(event_fields):
        invalid_fields.append("fields")
    dedupe_key = payload.get("dedupe_key")
    if dedupe_key is not None and not isinstance(dedupe_key, str):
        invalid_fields.append("dedupe_key")
    url = payload.get("url")
    if url is not None and (not isinstance(url, str) or not url.startswith(ALLOWED_URL_PREFIX)
                            or len(url) > URL_MAX_LENGTH):
        invalid_fields.append("url")
    return invalid_fields


def _is_valid_event_fields(event_fields) -> bool:
    """fields 형태 확인: [{name, value}] 문자열 쌍, 개수·길이 상한 이내"""
    if not isinstance(event_fields, list) or len(event_fields) > EVENT_FIELDS_MAX_COUNT:
        return False
    return all(
        isinstance(field, dict) and isinstance(field.get("name"), str) and isinstance(field.get("value"), str)
        and 0 < len(field["name"]) <= EVENT_FIELD_NAME_MAX_LENGTH
        and 0 < len(field["value"]) <= EVENT_FIELD_VALUE_MAX_LENGTH
        for field in event_fields)


def _sanitize_log_value(value: str) -> str:
    """로그용 값 정리 (제어문자·비ASCII > ?, 50자 제한)"""
    return "".join(character if character.isprintable() and character.isascii() else "?"
                   for character in value[:50])
