"""관제소 런타임 보관: 라우터·폴러가 공유하는 의존 묶음 1개 (프로세스 전역, 미설정 시 None)"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from service.control_tower.registry import Registry


@dataclass
class ControlTowerRuntime:
    registry_provider: Callable[[], Registry]
    store: object  # ControlTowerStore
    dispatcher: object  # EventDispatcher


_runtime: ControlTowerRuntime | None = None


def set_runtime(runtime: ControlTowerRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> ControlTowerRuntime | None:
    return _runtime
