"""관제소 디스코드 임베드 변환: Notification > 임베드 dict (순수 함수, 길이 제한·심각도 색·복구 다운 시간 필드)"""
from __future__ import annotations

from service.control_tower.alert_planner import Notification

# 임베드 색: 심각도별 (critical 빨강, recovered 초록, warning 주황, info 회색)
EMBED_COLOR_BY_SEVERITY = {
    "critical": 0xE5484D,
    "recovered": 0x30A46C,
    "warning": 0xF5A524,
    "info": 0x8B8D98,
}
# 임베드 제목 최대 길이 (디스코드 제한 256자)
TITLE_MAX_LENGTH = 256
# 임베드 본문 최대 길이 (디스코드 제한 4096자, 여유 포함)
DESCRIPTION_MAX_LENGTH = 4000
FOOTER_TEXT = "SUH 관제소"
ELLIPSIS = "…"
SEVERITY_RECOVERED = "recovered"
# 복구 본문의 다운 시간 줄 접두 (alert_texts.recovery_body 형식과 동일)
DOWNTIME_LINE_PREFIX = "다운 시간: "
DOWNTIME_FIELD_NAME = "다운 시간"


def to_embed(notification: Notification, status_page_url: str) -> dict:
    """알림 1건 > 임베드: 색 > 제목·본문 자르기 > 알림 fields·복구 다운 시간 필드 > 링크·푸터"""
    description = notification.body
    downtime_text = None
    if notification.severity == SEVERITY_RECOVERED:
        description, downtime_text = _split_downtime_line(description)

    embed: dict = {
        "title": _truncate(notification.title, TITLE_MAX_LENGTH),
        "description": _truncate(description, DESCRIPTION_MAX_LENGTH),
        "color": EMBED_COLOR_BY_SEVERITY.get(notification.severity, EMBED_COLOR_BY_SEVERITY["info"]),
        "footer": {"text": FOOTER_TEXT},
    }
    # 알림 fields > 복구 다운 시간 (다운 시간은 항상 마지막)
    embed_fields = [{"name": name, "value": value, "inline": True} for name, value in notification.fields]
    if downtime_text:
        embed_fields.append({"name": DOWNTIME_FIELD_NAME, "value": downtime_text, "inline": True})
    if embed_fields:
        embed["fields"] = embed_fields
    link_url = notification.link_url or status_page_url
    if link_url:
        embed["url"] = link_url
    return embed


def _split_downtime_line(body: str) -> tuple[str, str | None]:
    """본문 > (다운 시간 줄 제외 본문, 다운 시간 값), 줄이 없으면 (원문, None)"""
    remaining_lines: list[str] = []
    downtime_text = None
    for line in body.split("\n"):
        if downtime_text is None and line.startswith(DOWNTIME_LINE_PREFIX):
            downtime_text = line[len(DOWNTIME_LINE_PREFIX):].strip() or None
        else:
            remaining_lines.append(line)
    if downtime_text is None:
        return body, None
    return "\n".join(remaining_lines), downtime_text


def _truncate(text: str, max_length: int) -> str:
    """최대 길이 초과 시 끝을 '…'로 대체 (결과 길이 = max_length)"""
    if len(text) <= max_length:
        return text
    return text[:max_length - len(ELLIPSIS)] + ELLIPSIS
