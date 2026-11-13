"""시각 <-> UTC ISO 문자열 변환 (저장소·메타 공용, 고정 형식이라 문자열 비교 = 시각 비교)"""
from __future__ import annotations

from datetime import datetime, timezone


def to_utc_text(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def from_utc_text(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None
