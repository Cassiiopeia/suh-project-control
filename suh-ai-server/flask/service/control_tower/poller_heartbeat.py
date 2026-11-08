"""관제소 폴러 심박 단계: 공개 장애 조립 > 심박 전송 > 결과 3종 분류 > meta 기록 > 거절 알림 > 새 외부 결과
결과 3종: 성공(집 인터넷 정상), 연결 실패·타임아웃(집 인터넷 실패), 거절·예외(집 인터넷 데이터 없음, R31)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping

from service.control_tower.check_runner import CheckResult
from service.control_tower.heartbeat_client import HeartbeatRejectedError, HeartbeatResponse
from service.control_tower.meta_keys import META_KEY_HEARTBEAT_IS_OK, META_KEY_HEARTBEAT_LAST_OK_AT
from service.control_tower.poller_steps import build_public_incidents, fresh_external_results, heartbeat_check_result
from service.control_tower.registry import MaintenanceWindow, Registry
from service.control_tower.system_alerts import (
    ConditionAlert, build_heartbeat_recovered_notice, build_heartbeat_rejected_alert,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HeartbeatOutcome:
    home_network_check: CheckResult | None  # 집 인터넷 관측 (미설정·거절·예외 > None = 데이터 없음)
    external_results: dict[str, CheckResult] = field(default_factory=dict)  # 이번에 처음 받은 Worker 외부 결과


NO_HEARTBEAT = HeartbeatOutcome(None)


class HeartbeatStep:
    def __init__(self, heartbeat_client, store, dispatcher):
        self._heartbeat_client = heartbeat_client  # None이면 심박·외부 결과·집 인터넷 판정 없음
        self._store = store
        self._rejection_alert = ConditionAlert(dispatcher, build_heartbeat_rejected_alert,
                                               build_heartbeat_recovered_notice)
        self._last_applied_external_checked_at: datetime | None = None  # 같은 Worker 결과 중복 반영 방지

    def run(self, registry: Registry, maintenance: Mapping[str, MaintenanceWindow], now: datetime) -> HeartbeatOutcome:
        """심박 1회: 전송 > 분류 > meta 기록 > 거절 알림(거절 상태별 1회, 성공 시 정상화) > 관측·외부 결과"""
        if self._heartbeat_client is None:
            return NO_HEARTBEAT
        public_incidents = self._public_incidents(registry, maintenance, now)
        response, is_connection_failure, rejection_status = None, False, None
        try:
            response = self._heartbeat_client.send(registry, public_incidents, now, tuple(maintenance.values()),
                                                   project_icons=self._project_icons())
            is_connection_failure = response is None
        except HeartbeatRejectedError as error:
            rejection_status = error.rejection_status
        except Exception as error:  # 심박 코드 자체 오류: 집 인터넷 장애로 보지 않음
            logger.warning("[control-tower poller] heartbeat crashed : %s", type(error).__name__)

        self._record_meta(response is not None, now)
        if response is not None:
            self._rejection_alert.report(None, now)
        elif rejection_status is not None:
            self._rejection_alert.report(rejection_status, now)

        if response is None and not is_connection_failure:
            return NO_HEARTBEAT
        return HeartbeatOutcome(heartbeat_check_result(response is not None, now),
                                self._take_external_results(response, now))

    def _public_incidents(self, registry: Registry, maintenance: Mapping[str, MaintenanceWindow],
                          now: datetime) -> list[dict]:
        """공개 장애 (로컬 DB 조회 실패는 심박 실패가 아님 > 빈 목록)"""
        try:
            return build_public_incidents(registry, self._store, maintenance, now)
        except Exception as error:
            logger.warning("[control-tower poller] public incidents read failed : %s", type(error).__name__)
            return []

    def _project_icons(self) -> dict[str, bytes]:
        """프로젝트 썸네일 (로컬 DB 조회 실패는 심박 실패가 아님 > 썸네일 없이 전송)"""
        try:
            return self._store.load_project_icon_images()
        except Exception as error:
            logger.warning("[control-tower poller] project icons read failed : %s", type(error).__name__)
            return {}

    def _record_meta(self, is_heartbeat_ok: bool, now: datetime) -> None:
        self._store.set_meta(META_KEY_HEARTBEAT_IS_OK, "1" if is_heartbeat_ok else "0")
        if is_heartbeat_ok:
            self._store.set_meta(META_KEY_HEARTBEAT_LAST_OK_AT, now.isoformat())

    def _take_external_results(self, response: HeartbeatResponse | None, now: datetime) -> dict[str, CheckResult]:
        """새 외부 결과만 꺼내고 반영한 checked_at 기억"""
        external_results = fresh_external_results(response, now, self._last_applied_external_checked_at)
        if external_results:
            self._last_applied_external_checked_at = response.checked_at
        return external_results
