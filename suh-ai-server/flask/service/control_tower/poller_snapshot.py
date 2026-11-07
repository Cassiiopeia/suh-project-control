"""관제소 폴러 현재 상태 뷰: 폴러 스레드가 틱마다 통째로 교체, 요청 스레드는 읽기만 (수정 불가 매핑)"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Mapping

from service.control_tower.registry import Registry
from service.control_tower.state_machine import Observation, ServiceState


@dataclass(frozen=True)
class PublishedView:
    states: Mapping[str, ServiceState]
    observations: Mapping[str, Observation]  # service_id > 마지막 관측 (점검 대상 없는 서비스는 없음)
    last_tick_at: datetime | None


@dataclass(frozen=True)
class PollerSnapshot:
    registry: Registry | None  # 등록 파일을 한 번도 못 읽었으면 None
    states: Mapping[str, ServiceState]
    observations: Mapping[str, Observation]
    last_tick_at: datetime | None


# 첫 틱 전 뷰
EMPTY_VIEW = PublishedView(MappingProxyType({}), MappingProxyType({}), None)
