"""관제소 알림 발송 단일 지점: 플래너 알림·앱 이벤트 > 바인딩 채널 > 디스코드 임베드
이벤트 입구는 검증 > 중복 억제 > 발송 순서, 플래너 알림은 중복 억제 없이 바로 발송
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from service.control_tower.alert_planner import GLOBAL_SCOPE, INFRASTRUCTURE_KIND, Notification
from service.control_tower.discord_messages import to_embed

logger = logging.getLogger(__name__)

# 이벤트 kind 허용 목록
EVENT_KINDS = ("report", "error", "deploy", "status", "info")
# 이벤트 severity 허용 목록
EVENT_SEVERITIES = ("info", "warning", "critical")
# info 이벤트는 프로젝트 상태 채널로
INFO_EVENT_KIND = "info"
STATUS_CHANNEL_KIND = "status"
# 이벤트 제목 길이 범위 (글자 수)
TITLE_MIN_LENGTH = 1
TITLE_MAX_LENGTH = 200
# 이벤트 본문 최대 길이 (글자 수)
BODY_MAX_LENGTH = 2000
# 이벤트 링크는 https만 허용
ALLOWED_URL_PREFIX = "https://"
HTTP_ACCEPTED = 202
HTTP_BAD_REQUEST = 400


class EventDispatcher:
    def __init__(self, registry_provider: Callable, store, discord_client_provider: Callable,
                 status_page_url: str):
        self._registry_provider = registry_provider
        self._store = store
        self._discord_client_provider = discord_client_provider
        self._status_page_url = status_page_url

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

    def accept_event(self, project_id: str, payload: dict, now: datetime) -> tuple[int, dict]:
        """앱 이벤트 접수: 검증 > 중복 억제 기록 > 발송 (발송 실패해도 접수 응답)"""
        invalid_fields = validate_event_payload(payload)
        if invalid_fields:
            return HTTP_BAD_REQUEST, {"error": "invalid", "fields": invalid_fields}

        dedupe_key = payload.get("dedupe_key") or ""
        if not self._store.record_event(project_id, payload["kind"], dedupe_key, now):
            return HTTP_ACCEPTED, {"accepted": True, "deduplicated": True}

        notification = Notification(
            scope=project_id, kind=payload["kind"], severity=payload["severity"], title=payload["title"],
            body=payload.get("body") or "", service_ids=(), dedupe_key=dedupe_key, link_url=payload.get("url"))
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


def validate_event_payload(payload: dict) -> list[str]:
    """이벤트 필드 검증: 잘못된 필드 이름 목록 (kind, severity, title, body, dedupe_key, url 순)"""
    invalid_fields: list[str] = []
    if payload.get("kind") not in EVENT_KINDS:
        invalid_fields.append("kind")
    if payload.get("severity") not in EVENT_SEVERITIES:
        invalid_fields.append("severity")
    title = payload.get("title")
    if not isinstance(title, str) or not TITLE_MIN_LENGTH <= len(title) <= TITLE_MAX_LENGTH:
        invalid_fields.append("title")
    body = payload.get("body")
    if body is not None and (not isinstance(body, str) or len(body) > BODY_MAX_LENGTH):
        invalid_fields.append("body")
    dedupe_key = payload.get("dedupe_key")
    if dedupe_key is not None and not isinstance(dedupe_key, str):
        invalid_fields.append("dedupe_key")
    url = payload.get("url")
    if url is not None and (not isinstance(url, str) or not url.startswith(ALLOWED_URL_PREFIX)):
        invalid_fields.append("url")
    return invalid_fields


def _sanitize_log_value(value: str) -> str:
    """로그용 값 정리 (제어문자·비ASCII > ?, 50자 제한)"""
    return "".join(character if character.isprintable() and character.isascii() else "?"
                   for character in value[:50])
