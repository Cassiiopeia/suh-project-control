"""관제소 디스코드 임베드: 색 매핑, 제목·본문 길이 자르기, 복구 다운 시간 필드, 상태 페이지 링크"""
from __future__ import annotations

import pytest

from service.control_tower.alert_planner import Notification
from service.control_tower.discord_messages import (
    DESCRIPTION_MAX_LENGTH, EMBED_COLOR_BY_SEVERITY, FOOTER_TEXT, TITLE_MAX_LENGTH, to_embed,
)

STATUS_PAGE_URL = "https://status.example.com"


def _notification(severity: str = "critical", title: str = "이룸 API 다운", body: str = "원인: 연결 실패") -> Notification:
    return Notification("elum", "status", severity, title, body, ("elum-api",), "elum-api:down:2026-11-06T00:00:00+00:00")


@pytest.mark.parametrize("severity,expected_color", [
    ("critical", 0xE5484D), ("recovered", 0x30A46C), ("warning", 0xF5A524), ("info", 0x8B8D98),
])
def test_color_follows_severity(severity, expected_color):
    assert to_embed(_notification(severity), STATUS_PAGE_URL)["color"] == expected_color


def test_unknown_severity_falls_back_to_info_color():
    assert to_embed(_notification("mystery"), STATUS_PAGE_URL)["color"] == EMBED_COLOR_BY_SEVERITY["info"]


def test_title_and_description_are_truncated_with_ellipsis():
    embed = to_embed(_notification(title="가" * 300, body="나" * 5000), STATUS_PAGE_URL)
    assert len(embed["title"]) == TITLE_MAX_LENGTH and embed["title"].endswith("…")
    assert len(embed["description"]) == DESCRIPTION_MAX_LENGTH and embed["description"].endswith("…")


def test_short_text_is_kept_as_is():
    embed = to_embed(_notification(), STATUS_PAGE_URL)
    assert embed["title"] == "이룸 API 다운"
    assert embed["description"] == "원인: 연결 실패"


def test_recovery_embed_has_downtime_field_without_duplicate_line():
    body = "원인: 연결 실패\n시작: 2026-11-06 09:00\n다운 시간: 1시간 12분"
    embed = to_embed(_notification("recovered", body=body), STATUS_PAGE_URL)
    assert embed["fields"] == [{"name": "다운 시간", "value": "1시간 12분", "inline": True}]
    assert "다운 시간" not in embed["description"]
    assert embed["description"] == "원인: 연결 실패\n시작: 2026-11-06 09:00"


def test_recovery_without_downtime_line_has_no_fields():
    assert "fields" not in to_embed(_notification("recovered"), STATUS_PAGE_URL)


def test_non_recovery_keeps_downtime_line_in_description():
    body = "다운 시간: 5분"
    embed = to_embed(_notification("critical", body=body), STATUS_PAGE_URL)
    assert "fields" not in embed and embed["description"] == body


def test_url_only_when_status_page_url_given():
    assert to_embed(_notification(), STATUS_PAGE_URL)["url"] == STATUS_PAGE_URL
    assert "url" not in to_embed(_notification(), "")


def test_footer_is_control_tower():
    assert to_embed(_notification(), STATUS_PAGE_URL)["footer"] == {"text": FOOTER_TEXT} and FOOTER_TEXT == "SUH 관제소"
