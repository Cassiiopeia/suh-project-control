"""관제소 자체 상태 전역 알림: 등록 파일 오류, Worker 심박 거절 (#관제-긴급)
조건 1종당 ConditionAlert 1개: 새 조건 값 > 경고 1건, 조건 해소 > 정상화 안내 1건
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from service.control_tower.alert_planner import (
    GLOBAL_SCOPE, INFRASTRUCTURE_KIND, SEVERITY_CRITICAL, SEVERITY_INFO, Notification,
)

logger = logging.getLogger(__name__)

REGISTRY_ERROR_TITLE = "[관제소] 등록 파일 오류"
REGISTRY_RECOVERED_TITLE = "[관제소] 등록 파일 정상화"
HEARTBEAT_RECOVERED_TITLE = "[관제소] Worker 심박 정상화"


def build_registry_error_alert(first_problem: str, now: datetime) -> Notification:
    """등록 파일 오류 경고: 본문 = 첫 문제 1줄 (env 값·비밀값 없음, 이전 등록 정보로 계속)"""
    return _global_notification(SEVERITY_CRITICAL, REGISTRY_ERROR_TITLE,
                                f"{first_problem}\n이전에 읽은 등록 정보로 계속 감시 (처음이면 감시 중지)",
                                f"system:registry-error:{now.isoformat()}")


def build_registry_recovered_notice(_previous_condition: str, now: datetime) -> Notification:
    return _global_notification(SEVERITY_INFO, REGISTRY_RECOVERED_TITLE, "등록 파일 다시 읽기 성공",
                                f"system:registry-recovered:{now.isoformat()}")


def build_heartbeat_rejected_alert(rejection_status: str, now: datetime) -> Notification:
    """심박 거절 경고: Worker 응답 상태 (집 인터넷 판정 보류)"""
    return _global_notification(
        SEVERITY_CRITICAL, f"[관제소] Worker 심박 거절 ({rejection_status})",
        f"Worker 응답: {rejection_status}\n집 인터넷 판정 보류 (심박 비밀키·Worker 주소·Worker 배포 확인 필요)",
        f"system:heartbeat-rejected:{now.isoformat()}")


def build_heartbeat_recovered_notice(previous_status: str, now: datetime) -> Notification:
    return _global_notification(SEVERITY_INFO, HEARTBEAT_RECOVERED_TITLE, f"심박 수신 재개 (직전 거절: {previous_status})",
                                f"system:heartbeat-recovered:{now.isoformat()}")


class ConditionAlert:
    """조건 1종 전역 알림: 조건 값이 바뀔 때만 발송 (값 > 경고, None > 정상화)
    발송 실패 > 다음 보고에 재시도, 디스코드 미설정 > 재시도 안 함"""

    def __init__(self, dispatcher, build_alert: Callable[[str, datetime], Notification],
                 build_recovery: Callable[[str, datetime], Notification], reported_condition: str | None = None):
        self._dispatcher = dispatcher
        self._build_alert = build_alert
        self._build_recovery = build_recovery
        self._reported_condition = reported_condition  # 마지막으로 알린 조건 (None = 정상)

    @property
    def reported_condition(self) -> str | None:
        return self._reported_condition

    def report(self, condition: str | None, now: datetime, detail: str | None = None) -> None:
        """현재 조건 보고: 같으면 무시 > 새 조건이면 경고(본문 detail, 없으면 condition) > 해소면 정상화"""
        if condition == self._reported_condition:
            return
        if condition is None:
            notification = self._build_recovery(self._reported_condition, now)
        else:
            notification = self._build_alert(detail if detail is not None else condition, now)
        if self._deliver(notification) or not self._dispatcher.is_delivery_configured():
            self._reported_condition = condition

    def _deliver(self, notification: Notification) -> bool:
        """발송 1건 (예외는 실패로 기록)"""
        try:
            return self._dispatcher.dispatch(notification) is True
        except Exception as error:
            logger.warning("[control-tower system alert] dispatch failed : %s", type(error).__name__)
            return False


def _global_notification(severity: str, title: str, body: str, dedupe_key: str) -> Notification:
    return Notification(GLOBAL_SCOPE, INFRASTRUCTURE_KIND, severity, title, body, (), dedupe_key)
