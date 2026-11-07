"""관제소 알림 문구: 제목, 본문(원인·시작 시각·다운 시간·영향 서비스), 기간 한국어 표기"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
KST_TIME_FORMAT = "%Y-%m-%d %H:%M KST"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# 장애 원인 코드 > 표시 문구
CAUSE_LABELS = {
    "service_down": "서비스 다운",
    "external_path": "바깥 연결 문제 (프록시/포트포워딩/DNS)",
    "unreachable": "접속 불가",
}
UNKNOWN_CAUSE_LABEL = "알 수 없음"


def format_duration_korean(seconds: float) -> str:
    """초 > 큰 단위 2개까지 한국어 (예: 2일 3시간, 1시간 12분, 5분, 1분 미만)"""
    total_seconds = int(seconds)
    days, remainder = divmod(total_seconds, SECONDS_PER_DAY)
    hours, remainder = divmod(remainder, SECONDS_PER_HOUR)
    minutes = remainder // SECONDS_PER_MINUTE
    if days:
        return _join_units((days, "일"), (hours, "시간"))
    if hours:
        return _join_units((hours, "시간"), (minutes, "분"))
    if minutes:
        return f"{minutes}분"
    return "1분 미만"


def _join_units(major: tuple[int, str], minor: tuple[int, str]) -> str:
    """큰 단위 + 작은 단위 (작은 단위 0이면 생략)"""
    text = f"{major[0]}{major[1]}"
    return text if not minor[0] else f"{text} {minor[0]}{minor[1]}"


def format_kst(moment: datetime) -> str:
    """시각 > YYYY-MM-DD HH:MM KST"""
    return moment.astimezone(KST).strftime(KST_TIME_FORMAT)


def down_title(service_name: str) -> str:
    return f"[다운] {service_name}"


def reminder_title(service_name: str) -> str:
    return f"[계속 다운] {service_name}"


def recovery_title(service_name: str) -> str:
    return f"[복구] {service_name}"


def down_body(cause: str | None, since: datetime, affected_names: list[str]) -> str:
    """down 본문: 원인 > 시작 > 영향 서비스"""
    return _join_lines(_outage_lines(cause, since), _name_list_line("영향 서비스", affected_names))


def reminder_body(cause: str | None, since: datetime, now: datetime, affected_names: list[str]) -> str:
    """재알림 본문: 원인 > 시작 > 다운 지속 > 영향 서비스"""
    elapsed_line = f"다운 지속: {format_duration_korean((now - since).total_seconds())}"
    return _join_lines(_outage_lines(cause, since), elapsed_line, _name_list_line("영향 서비스", affected_names))


def recovery_body(cause: str | None, since: datetime, now: datetime, recovered_child_names: list[str]) -> str:
    """복구 본문: 원인 > 시작 > 다운 시간 > 함께 복구된 서비스"""
    downtime_line = f"다운 시간: {format_duration_korean((now - since).total_seconds())}"
    return _join_lines(_outage_lines(cause, since), downtime_line,
                       _name_list_line("함께 복구된 서비스", recovered_child_names))


def _outage_lines(cause: str | None, since: datetime) -> str:
    cause_label = CAUSE_LABELS.get(cause or "", UNKNOWN_CAUSE_LABEL)
    return f"원인: {cause_label}\n시작: {format_kst(since)}"


def _name_list_line(label: str, names: list[str]) -> str:
    """이름 목록 > '{label} N개: a, b' (없으면 빈 문자열)"""
    return f"{label} {len(names)}개: {', '.join(names)}" if names else ""


def _join_lines(*lines: str) -> str:
    return "\n".join(line for line in lines if line)
