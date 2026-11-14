"""디스코드 동기화용 실효 등록 정보 단일 원본: 등록 파일 원본 + 지금 저장소 덮어쓰기 > 준비 확인
관리 화면 동기화 버튼·알림 종류 변경 후 동기화 공용 (DISCORD_SYNC_LOCK 안에서 호출)"""
from __future__ import annotations

from service.control_tower.registry import Registry
from service.control_tower.registry_overrides import apply_overrides


def load_sync_ready_registry(runtime) -> Registry | None:
    """실효 등록 정보 재조립 > 준비 안 됨이면 None
    폴러 캐시는 방금 저장한 덮어쓰기·알림 종류를 다음 틱 전까지 모름 > 저장소를 다시 병합"""
    file_registry_provider = runtime.file_registry_provider or runtime.registry_provider
    registry = apply_overrides(file_registry_provider(), runtime.store)
    return registry if _is_registry_ready(runtime, registry) else None


def _is_registry_ready(runtime, registry: Registry) -> bool:
    """등록 파일을 한 번이라도 읽음 + 프로젝트 1개 이상 (빈 등록 정보 동기화는 기존 카테고리 전부 보관 처리)"""
    is_file_loaded = runtime.poller is None or runtime.poller.snapshot().registry is not None
    return is_file_loaded and bool(registry.projects)
