"""관제소 시간대 단일 원본: KST (일자 경계·요약 시각·알림 표기)"""
from __future__ import annotations

from datetime import timedelta, timezone

KST = timezone(timedelta(hours=9))
