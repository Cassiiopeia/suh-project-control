"""디스코드 동기화 + 사용자 정의 알림 종류 (순수): 제거된 종류 바인딩 판정, 보관 대상 채널 찾기
보관은 이름 변경 없이 관리자만 권한 (빠진 프로젝트 하위 채널과 같은 방식, 디스코드 이름 정규화와 무관하게 멱등)
"""
from __future__ import annotations

from service.control_tower.discord_sync_models import ROLE_KIND_PREFIX
from service.control_tower.registry import Registry
from service.control_tower.registry_models import RESERVED_EVENT_KINDS


class RemovedEventKindFinder:
    """등록 프로젝트에서 빠진 사용자 정의 종류: 바인딩 판정, 보관할 채널 목록"""

    def __init__(self, registry: Registry):
        # 등록 프로젝트 id > 현재 사용자 정의 종류 이름
        self._event_kind_names_by_project = {
            project.id: frozenset(event_kind.kind for event_kind in project.event_kinds)
            for project in registry.projects
        }

    def is_removed_event_kind(self, scope: str, kind: str) -> bool:
        """사용자 정의 종류였는데 지금 없는 바인딩 (예약 종류·역할·미등록 프로젝트 scope는 아님)"""
        event_kind_names = self._event_kind_names_by_project.get(scope)
        if event_kind_names is None or kind in RESERVED_EVENT_KINDS or kind.startswith(ROLE_KIND_PREFIX):
            return False
        return kind not in event_kind_names

    def find_archivable_channels(self, bindings: dict[tuple[str, str], str], channel_by_id: dict[str, dict],
                                 claimed_channel_ids: set[str]) -> list[tuple[str, str, dict]]:
        """보관 대상 (scope, kind, 채널): 제거된 종류 바인딩 중 채널이 남아 있고 다른 키가 가져가지 않은 것 (정렬 순)"""
        return [(scope, kind, channel_by_id[channel_id]) for (scope, kind), channel_id in sorted(bindings.items())
                if self.is_removed_event_kind(scope, kind)
                and channel_id in channel_by_id and channel_id not in claimed_channel_ids]
