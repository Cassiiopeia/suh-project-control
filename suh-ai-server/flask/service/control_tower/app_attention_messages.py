"""앱 확인할 일 디스코드 알림 문구: 알림 줄 > 채널 종류별 Notification, 소스 연동 끊김·복구 > Notification
순수 함수. 본문은 임베드 본문 한도 안 (넘치면 높은 수준 줄부터 남기고 "외 N건")"""
from __future__ import annotations

from service.control_tower.alert_planner import (
    GLOBAL_SCOPE, INFRASTRUCTURE_KIND, SEVERITY_CRITICAL, SEVERITY_INFO, SEVERITY_RECOVERED, Notification,
)
from service.control_tower.app_attention_effective import LEVEL_CRITICAL, level_rank
from service.control_tower.app_attention_rules import SOURCE_HEALTH_RECOVERED, AlertLine
from service.control_tower.discord_messages import DESCRIPTION_MAX_LENGTH

# 수준 > 알림 심각도 (alert_planner에 warning 상수 없음, discord_messages 색 키와 같은 값)
SEVERITY_WARNING = "warning"
SEVERITY_BY_LEVEL = {"info": SEVERITY_INFO, "warning": SEVERITY_WARNING, "critical": SEVERITY_CRITICAL}
# 연동 끊김·복구 알림 채널 종류 (프로젝트 error 채널)
SOURCE_HEALTH_CHANNEL_KIND = "error"
LINE_PREFIX = "• "
# 본문이 넘칠 때 마지막 줄 (예: "외 3건")
OVERFLOW_LINE_FORMAT = "외 {count}건"
# 디스코드 마크다운 링크 이름에서 깨지는 글자
LINK_LABEL_ESCAPES = {"[": "\\[", "]": "\\]"}
# 링크 주소의 닫는 괄호 (마크다운 링크 끝으로 읽힘)
LINK_URL_ESCAPES = {"(": "%28", ")": "%29"}


def build_item_notifications(project_id: str, project_name: str, source_id: str, lines: list[AlertLine],
                             dedupe_suffix: str) -> list[Notification]:
    """알림 줄 > 채널 종류별 1건 (등장 순서) + critical 줄 있으면 전역 긴급 1건 (critical 줄만)"""
    lines_by_channel_kind: dict[str, list[AlertLine]] = {}
    for line in lines:
        lines_by_channel_kind.setdefault(line.channel_kind, []).append(line)
    title = f"{project_name} 확인할 일"
    dedupe_prefix = f"attention:{project_id}:{source_id}:{dedupe_suffix}"
    notifications = [
        _build_notification(project_id, channel_kind, title, channel_lines, f"{dedupe_prefix}:{channel_kind}")
        for channel_kind, channel_lines in lines_by_channel_kind.items()
    ]
    critical_lines = [line for line in lines if line.level == LEVEL_CRITICAL]
    if critical_lines:
        notifications.append(_build_notification(GLOBAL_SCOPE, INFRASTRUCTURE_KIND, title, critical_lines,
                                                  f"{dedupe_prefix}:{GLOBAL_SCOPE}"))
    return notifications


def build_source_health_notification(project_id: str, project_name: str, source_id: str, verdict: str,
                                     reason: str | None) -> Notification:
    """연동 판정 > 프로젝트 error 채널 1건 (끊김 = warning + 사유, 복구 = recovered)"""
    is_recovered = verdict == SOURCE_HEALTH_RECOVERED
    status_text = "연동 복구" if is_recovered else "연동 끊김"
    body = f"소스 {source_id}"
    if reason and not is_recovered:
        body += f"\n사유: {reason}"
    return Notification(
        scope=project_id, kind=SOURCE_HEALTH_CHANNEL_KIND,
        severity=SEVERITY_RECOVERED if is_recovered else SEVERITY_WARNING,
        title=f"{project_name} 확인할 일 {status_text}", body=body, service_ids=(),
        dedupe_key=f"attention:{project_id}:{source_id}:{verdict}",
    )


def _build_notification(scope: str, kind: str, title: str, lines: list[AlertLine], dedupe_key: str) -> Notification:
    """줄 묶음 > Notification (심각도 = 최고 수준, 링크 = 표시 순서 첫 admin_url)"""
    ordered_lines = sorted(lines, key=lambda line: level_rank(line.level), reverse=True)
    highest_level = ordered_lines[0].level
    link_url = next((line.admin_url for line in ordered_lines if line.admin_url), None)
    return Notification(
        scope=scope, kind=kind, severity=SEVERITY_BY_LEVEL.get(highest_level, SEVERITY_INFO), title=title,
        body=_build_body(ordered_lines), service_ids=(), dedupe_key=dedupe_key, link_url=link_url,
    )


def _build_body(ordered_lines: list[AlertLine]) -> str:
    """줄 목록(높은 수준 먼저) > 본문, 한도 넘으면 들어가는 줄까지 + "외 N건" (그 줄 자리 미리 확보)"""
    texts = [_format_line(line) for line in ordered_lines]
    full_body = "\n".join(texts)
    if len(full_body) <= DESCRIPTION_MAX_LENGTH:
        return full_body
    kept_texts: list[str] = []
    for index, text in enumerate(texts):
        overflow_text = OVERFLOW_LINE_FORMAT.format(count=len(texts) - index - 1)
        candidate = "\n".join(kept_texts + [text, overflow_text])
        if len(candidate) > DESCRIPTION_MAX_LENGTH:
            break
        kept_texts.append(text)
    overflow_text = OVERFLOW_LINE_FORMAT.format(count=len(texts) - len(kept_texts))
    return "\n".join(kept_texts + [overflow_text])


def _format_line(line: AlertLine) -> str:
    """알림 줄 > "• [label](admin_url) text" (주소 없으면 링크 없이)"""
    label = line.label
    if line.admin_url:
        label = f"[{_escape(label, LINK_LABEL_ESCAPES)}]({_escape(line.admin_url, LINK_URL_ESCAPES)})"
    return f"{LINE_PREFIX}{label} {line.text}"


def _escape(text: str, replacements: dict[str, str]) -> str:
    """글자 치환표 적용"""
    for original, replacement in replacements.items():
        text = text.replace(original, replacement)
    return text
