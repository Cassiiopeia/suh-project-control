"""관제소 받을 곳 중복 발송 방지: (프로젝트, 채널 종류, dedupe_key) > 마지막 발송 시각 (기억 기간 안 같은 알림은 생략)
기본 디스코드 발송 실패로 폴러·앱 확인할 일이 같은 알림을 다시 dispatch해도 받을 곳에는 1번만 (중복 발송보다 누락이 낫다)
dedupe_key 없는 알림은 같은 알림인지 알 수 없어 기억하지 않음 (매번 발송)"""
from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime, timedelta

from service.control_tower.alert_planner import Notification
from service.control_tower.event_dispatcher import to_channel_kind

# 같은 알림 기억 기간 (재발송 재시도 주기·재알림 간격보다 충분히 길게)
DELIVERED_NOTIFICATION_MEMORY_WINDOW = timedelta(hours=24)
# 기억 최대 항목 수 (초과 시 가장 오래된 것부터 삭제)
DELIVERED_NOTIFICATION_MEMORY_MAX_ENTRIES = 4096

NotificationIdentity = tuple[str, str, str]


def to_notification_identity(notification: Notification) -> NotificationIdentity:
    """알림 > 식별값: (프로젝트, 채널 종류, dedupe_key)"""
    return notification.scope, to_channel_kind(notification), notification.dedupe_key


class DeliveredNotificationMemory:
    """발송한 알림 식별값 기억 (스레드 안전, 기간·개수 제한)"""

    def __init__(self, window: timedelta = DELIVERED_NOTIFICATION_MEMORY_WINDOW,
                 max_entries: int = DELIVERED_NOTIFICATION_MEMORY_MAX_ENTRIES):
        self._window = window
        self._max_entries = max_entries
        self._delivered_at_by_identity: OrderedDict[NotificationIdentity, datetime] = OrderedDict()
        self._lock = threading.Lock()

    def remember_if_new(self, notification: Notification, now: datetime) -> bool:
        """dedupe_key 없음 True (기억 안 함) > 기간 지난 항목 정리 > 기간 안 같은 알림 False > 없으면 기억 후 True"""
        if not notification.dedupe_key:
            return True
        identity = to_notification_identity(notification)
        with self._lock:
            self._forget_expired(now)
            if identity in self._delivered_at_by_identity:
                return False
            self._delivered_at_by_identity[identity] = now
            while len(self._delivered_at_by_identity) > self._max_entries:
                self._delivered_at_by_identity.popitem(last=False)
            return True

    def _forget_expired(self, now: datetime) -> None:
        """추가 순서 = 시각 순서 > 앞에서부터 기간 지난 항목 삭제"""
        while self._delivered_at_by_identity:
            oldest_identity, delivered_at = next(iter(self._delivered_at_by_identity.items()))
            if now - delivered_at < self._window:
                return
            del self._delivered_at_by_identity[oldest_identity]
