"""디스코드 구조 동기화 실행: 역할 > 카테고리 > 채널 > 보관 순, 참조 > 실제 id 변환, 생성·매칭 즉시 바인딩 기록
실패 작업은 오류 목록에 남기고 계속 (실패·건너뛴 역할·카테고리에 기대는 작업은 건너뜀)
"""
from __future__ import annotations

import logging

from service.control_tower.discord_client import DiscordError
from service.control_tower.discord_sync_models import (
    ACTION_ARCHIVE_CATEGORY, ACTION_ARCHIVE_CHANNEL, ACTION_BIND, ACTION_CREATE_CATEGORY, ACTION_CREATE_CHANNEL,
    ACTION_CREATE_ROLE, ACTION_UPDATE_CHANNEL, CATEGORY_CHANNEL_TYPE, CATEGORY_KIND, ROLE_KIND_PREFIX,
    TEXT_CHANNEL_TYPE, SyncOperation, SyncReport, role_binding_key,
)

logger = logging.getLogger(__name__)

# 실행 단계: 0 역할, 1 카테고리, 2 채널, 3 보관
ROLE_PHASE = 0
CATEGORY_PHASE = 1
CHANNEL_PHASE = 2
ARCHIVE_PHASE = 3


class _DependencyUnavailable(Exception):
    """참조한 역할·카테고리가 실패했거나 아직 없음"""

    def __init__(self, reference: str):
        super().__init__(reference)
        self.reference = reference


def apply_sync(client, store, operations: list[SyncOperation]) -> SyncReport:
    """작업 목록 실행 (단계 순 정렬, 같은 단계는 계획 순서 유지) > 결과 집계"""
    applier = _SyncApplier(client, store)
    for operation in sorted(operations, key=_phase_of):
        applier.apply(operation)
    return applier.report


def _phase_of(operation: SyncOperation) -> int:
    if operation.action in (ACTION_ARCHIVE_CATEGORY, ACTION_ARCHIVE_CHANNEL):
        return ARCHIVE_PHASE
    if operation.action == ACTION_CREATE_ROLE or (operation.kind or "").startswith(ROLE_KIND_PREFIX):
        return ROLE_PHASE
    if operation.action == ACTION_CREATE_CATEGORY or operation.kind == CATEGORY_KIND:
        return CATEGORY_PHASE
    return CHANNEL_PHASE


class _SyncApplier:
    def __init__(self, client, store):
        self._client = client
        self._store = store
        self.report = SyncReport()
        # 바인딩 키 > 디스코드 id (실행 중 생성·매칭 결과 반영)
        self._discord_id_by_binding = dict(store.all_bindings())
        # 실패·건너뛴 역할·카테고리 바인딩 키
        self._unavailable_bindings: set[tuple[str, str]] = set()

    def apply(self, operation: SyncOperation) -> None:
        """작업 1건: 의존 확인 > 디스코드 호출 > 바인딩·집계 (실패는 오류 기록 후 반환)"""
        try:
            self._apply_operation(operation)
        except _DependencyUnavailable as error:
            self._mark_unavailable(operation)
            detail = f"skipped (dependency unavailable: {error.reference})"
            self._record_error(operation, detail, detail)
        except DiscordError as error:
            if operation.action in (ACTION_CREATE_ROLE, ACTION_CREATE_CATEGORY):
                self._mark_unavailable(operation)
            status_text = f"status {error.status_code}"
            self._record_error(operation, f"{status_text} {error.reason}".rstrip(), status_text)

    def _apply_operation(self, operation: SyncOperation) -> None:
        action = operation.action
        if action == ACTION_BIND:
            self._bind(operation, operation.target_id)
        elif action == ACTION_CREATE_ROLE:
            role = self._client.create_role(operation.name)
            self._bind(operation, str(role["id"]))
            self.report.created += 1
        elif action in (ACTION_CREATE_CATEGORY, ACTION_CREATE_CHANNEL):
            self._create_channel(operation)
            self.report.created += 1
        else:
            overwrites = self._resolve_overwrites(operation) + [dict(item) for item in operation.preserved_overwrites]
            self._client.edit_channel(operation.target_id, name=operation.name, permission_overwrites=overwrites)
            if action == ACTION_UPDATE_CHANNEL:
                self.report.updated += 1
            else:
                self.report.archived += 1

    def _create_channel(self, operation: SyncOperation) -> None:
        """카테고리·채널 생성 (부모 카테고리 참조 해석) > 바인딩"""
        is_category = operation.action == ACTION_CREATE_CATEGORY
        parent_id = None
        if operation.parent_scope is not None:
            parent_id = self._resolve_binding((operation.parent_scope, CATEGORY_KIND),
                                              f"{operation.parent_scope}:{CATEGORY_KIND}")
        overwrites = self._resolve_overwrites(operation)
        channel = self._client.create_channel(operation.name, CATEGORY_CHANNEL_TYPE if is_category else TEXT_CHANNEL_TYPE,
                                              parent_id, overwrites)
        self._bind(operation, str(channel["id"]))

    def _resolve_overwrites(self, operation: SyncOperation) -> list[dict]:
        """참조 > 실제 id, allow·deny는 디스코드 형식(문자열)"""
        resolved = []
        for overwrite in operation.overwrites:
            reference = overwrite.get("ref")
            overwrite_id = overwrite.get("id") if reference is None else self._resolve_binding(
                role_binding_key(reference), reference)
            resolved.append({"id": overwrite_id, "type": overwrite["type"],
                             "allow": str(overwrite["allow"]), "deny": str(overwrite["deny"])})
        return resolved

    def _resolve_binding(self, binding_key: tuple[str, str], reference: str) -> str:
        discord_id = self._discord_id_by_binding.get(binding_key)
        if binding_key in self._unavailable_bindings or discord_id is None:
            raise _DependencyUnavailable(reference)
        return discord_id

    def _bind(self, operation: SyncOperation, discord_id: str) -> None:
        if operation.kind is None:
            return
        self._store.set_binding(operation.scope, operation.kind, discord_id)
        self._discord_id_by_binding[(operation.scope, operation.kind)] = discord_id

    def _mark_unavailable(self, operation: SyncOperation) -> None:
        if operation.kind is not None:
            self._unavailable_bindings.add((operation.scope, operation.kind))

    def _record_error(self, operation: SyncOperation, detail: str, log_detail: str) -> None:
        """오류 1줄: '{작업} {scope}/{kind}: {사유}' (토큰·응답 본문 미포함, 로그엔 디스코드 사유 문구 제외)"""
        prefix = f"{operation.action} {operation.scope}/{operation.kind}"
        self.report.errors.append(f"{prefix}: {detail}")
        logger.warning("[control-tower discord sync] %s : %s", prefix, log_detail)
