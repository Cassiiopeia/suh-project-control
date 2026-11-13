"""프로젝트 이벤트 내부 발송: 서버 내부 코드가 HTTP 없이 접수 경로(검증, 중복 억제, 발송)를 그대로 사용"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from service.control_tower.event_dispatcher import EVENT_FIELD_VALUE_MAX_LENGTH
from service.control_tower.log_text import sanitize_log_value
from service.control_tower.runtime import get_runtime

logger = logging.getLogger(__name__)

# 접수 성공 응답 코드 (중복 억제된 접수 포함)
HTTP_ACCEPTED = 202


def send_project_event(project_id: str, kind: str, title: str, *,
                       fields: list[tuple[str, str | None]] = (), body: str = "",
                       severity: str = "info", url: str | None = None,
                       dedupe_key: str | None = None) -> bool:
    """프로젝트 이벤트 1건 발송: 런타임 확인 > 본문 조립 > 접수 (실패는 False + 경고 로그, 예외 없음)"""
    try:
        runtime = get_runtime()
        if runtime is None:
            logger.warning("[control-tower project event] skipped : runtime is not configured")
            return False
        payload = {
            "kind": kind, "severity": severity, "title": title, "body": body,
            # 값 없는 필드는 제외, 긴 값은 접수 상한으로 자름
            "fields": [{"name": name, "value": value[:EVENT_FIELD_VALUE_MAX_LENGTH]} for name, value in fields if value],
            "dedupe_key": dedupe_key, "url": url,
        }
        status, response = runtime.dispatcher.accept_event(project_id, payload, datetime.now(timezone.utc))
        if status != HTTP_ACCEPTED:
            logger.warning("[control-tower project event] rejected %s : project %s kind %s %s", status,
                           sanitize_log_value(project_id), sanitize_log_value(kind),
                           sanitize_log_value(str(response.get("error", ""))))
            return False
        return True
    except Exception as error:  # 호출한 업무 흐름을 막지 않음
        logger.warning("[control-tower project event] failed : project %s kind %s %s",
                       sanitize_log_value(str(project_id)), sanitize_log_value(str(kind)),
                       sanitize_log_value(repr(error)))
        return False
