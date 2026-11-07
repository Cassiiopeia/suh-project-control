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
    poller: object | None = None  # ControlTowerPoller (관리자 화면 현재 상태 조회용)
    discord_client_provider: Callable[[], object | None] | None = None  # 호출 시점의 DiscordClient (미설정이면 None)
    guild_id: str | None = None  # 디스코드 동기화 대상 서버 ID
    # 덮어쓰기 전 등록 파일 원본 (없으면 registry_provider 값을 원본으로 봄)
    file_registry_provider: Callable[[], Registry] | None = None


_runtime: ControlTowerRuntime | None = None


def set_runtime(runtime: ControlTowerRuntime | None) -> None:
    global _runtime
    _runtime = runtime


def get_runtime() -> ControlTowerRuntime | None:
    return _runtime
