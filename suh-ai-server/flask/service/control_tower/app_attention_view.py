"""앱 확인할 일 화면용 조립: 유효 항목(현황), 소스 목록·상태, 항목 + 덮어쓰기, 요약 숫자 > JSON dict
토큰 값은 싣지 않고 환경변수 이름과 설정 여부만, 꺼진 소스와 스냅샷에서 빠진 항목은 현황·요약에서 제외"""
from __future__ import annotations

import os
from dataclasses import dataclass

from service.control_tower.app_attention_effective import (
    LEVEL_CRITICAL, LEVEL_OK, EffectiveItem, level_rank, resolve_effective_item,
)
from service.control_tower.app_attention_models import SOURCE_MODE_PULL, SOURCE_MODE_PUSH, AttentionItem
from service.control_tower.app_attention_rules import SUCCESS_RESULTS
from service.control_tower.app_attention_store import (
    AttentionItemOverride, AttentionSource, AttentionSourceState, StoredAttentionItem,
)
from service.control_tower.app_attention_tokens import (
    event_token_env_name, is_pull_token_configured, pull_token_env_name,
)

LEVEL_WARNING = "warning"
STATE_OK = "ok"


@dataclass(frozen=True)
class ViewedItem:
    """저장된 항목 1건 + 덮어쓰기 반영 결과"""
    stored: StoredAttentionItem
    override: AttentionItemOverride | None
    effective: EffectiveItem

    @property
    def is_open(self) -> bool:
        return is_open_item(self.effective)


@dataclass(frozen=True)
class ProjectAttention:
    """프로젝트 1개의 켜진 소스와 현재 보고 중인 항목"""
    project_id: str
    project_name: str
    sources: list[tuple[AttentionSource, AttentionSourceState | None]]
    items: list[ViewedItem]

    @property
    def open_items(self) -> list[ViewedItem]:
        return [item for item in self.items if item.is_open and not item.effective.is_hidden]

    @property
    def failing_source_ids(self) -> list[str]:
        return [source.source_id for source, state in self.sources if is_failing_source(source, state)]


# ---- 판정 ----

def is_open_item(effective: EffectiveItem) -> bool:
    """열린 항목: 유효 수준 ok 아님 + kind별 조건 (count > 0, gauge 기준 넘김 또는 warning 이상, state ok 아님)"""
    item = effective.item
    if effective.level == LEVEL_OK:
        return False
    if item.kind == "count":
        return (item.count or 0) > 0
    if item.kind == "gauge":
        is_threshold_exceeded = effective.threshold is not None and item.value is not None \
            and item.value >= effective.threshold
        return is_threshold_exceeded or level_rank(effective.level) >= level_rank(LEVEL_WARNING)
    if item.kind == "state":
        return item.state is not None and item.state != STATE_OK
    return True  # 모르는 kind: 수준(info 이상)만으로 판정


def is_failing_source(source: AttentionSource, state: AttentionSourceState | None) -> bool:
    """실패 중인 소스: 켜져 있고 (마지막 결과가 성공 아님 또는 연동 끊김 알림 상태), 시도 전 소스는 제외"""
    if not source.is_enabled or state is None:
        return False
    is_last_failed = state.last_result is not None and state.last_result not in SUCCESS_RESULTS
    return is_last_failed or state.failure_alerted_at is not None


def to_attention_item(stored: StoredAttentionItem) -> AttentionItem:
    """저장 항목 > 규칙 평가용 항목 (raw는 평가에 쓰지 않아 생략)"""
    return AttentionItem(stored.key, stored.label, stored.kind, stored.level, stored.group, stored.description,
                         stored.admin_url, stored.latest_at, stored.detail, stored.count, stored.total, stored.value,
                         stored.limit, stored.unit, stored.state)


def view_source_items(store, source: AttentionSource, is_missing_included: bool = False) -> list[ViewedItem]:
    """소스 항목 + 덮어쓰기 > 유효 항목 목록 (key 순)"""
    overrides = store.load_attention_overrides(source.project_id, source.source_id)
    viewed_items = []
    for key, stored in store.load_attention_items(source.project_id, source.source_id).items():
        if stored.missing_since is not None and not is_missing_included:
            continue
        override = overrides.get(key)
        viewed_items.append(ViewedItem(stored, override, resolve_effective_item(to_attention_item(stored), override)))
    return viewed_items


def collect_project_attention(store, registry=None) -> list[ProjectAttention]:
    """켜진 소스가 있는 프로젝트만, 등록 순서 (등록에 없는 프로젝트는 id 순으로 뒤에, 이름 = id)"""
    states = store.list_attention_source_states()
    sources_by_project: dict[str, list] = {}
    for source in store.list_attention_sources():
        if source.is_enabled:
            sources_by_project.setdefault(source.project_id, []).append(
                (source, states.get((source.project_id, source.source_id))))
    name_by_project_id = {project.id: project.name for project in registry.projects} if registry is not None else {}
    ordered_project_ids = [project_id for project_id in name_by_project_id if project_id in sources_by_project]
    ordered_project_ids += sorted(set(sources_by_project) - set(ordered_project_ids))
    return [
        ProjectAttention(project_id, name_by_project_id.get(project_id, project_id), sources_by_project[project_id],
                         [item for source, _ in sources_by_project[project_id] for item in view_source_items(store, source)])
        for project_id in ordered_project_ids
    ]


# ---- 응답 조립 ----

def build_app_attention_summary(store) -> dict:
    """요약 숫자 4개: 열린 항목, 그중 warning·critical, 실패 중인 소스 (숨김·ok·0건 제외)"""
    projects = collect_project_attention(store)
    open_items = [item for project in projects for item in project.open_items]
    return {
        "open_item_count": len(open_items),
        "warning_count": sum(1 for item in open_items if item.effective.level == LEVEL_WARNING),
        "critical_count": sum(1 for item in open_items if item.effective.level == LEVEL_CRITICAL),
        "failing_source_count": sum(len(project.failing_source_ids) for project in projects),
    }


def build_app_attention_board(store, registry) -> dict:
    """현황: 프로젝트별 소스 상태 + 숨기지 않은 항목 (열린 항목, 높은 수준 먼저) + 요약"""
    projects = []
    for project in collect_project_attention(store, registry):
        visible_items = [item for item in project.items if not item.effective.is_hidden]
        visible_items.sort(key=lambda item: (not item.is_open, -level_rank(item.effective.level),
                                             item.stored.group or "", item.stored.key))
        projects.append({
            "id": project.project_id,
            "name": project.project_name,
            "open_item_count": len(project.open_items),
            "sources": [_board_source_entry(source, state) for source, state in project.sources],
            "items": [_board_item_entry(item) for item in visible_items],
        })
    return {"projects": projects, "summary": build_app_attention_summary(store)}


def build_source_list(store, registry) -> dict:
    """관리: 전체 소스 (꺼진 소스 포함) + 수집 상태 + 토큰 설정 여부"""
    states = store.list_attention_source_states()
    name_by_project_id = {project.id: project.name for project in registry.projects}
    return {"sources": [
        build_source_entry(store, source, states.get((source.project_id, source.source_id)),
                           name_by_project_id.get(source.project_id, source.project_id))
        for source in store.list_attention_sources()
    ]}


def build_source_entry(store, source: AttentionSource, state: AttentionSourceState | None, project_name: str) -> dict:
    """소스 1건: 설정 > 토큰 이름·설정 여부 > 항목 수 > 수집 상태"""
    is_pull_used = source.mode != SOURCE_MODE_PUSH
    is_push_used = source.mode != SOURCE_MODE_PULL
    is_pull_configured = is_pull_token_configured(source.project_id, source.source_id) if is_pull_used else None
    is_push_configured = bool(os.environ.get(event_token_env_name(source.project_id))) if is_push_used else None
    viewed_items = view_source_items(store, source)
    return {
        "project_id": source.project_id,
        "project_name": project_name,
        "source_id": source.source_id,
        "url": source.url or None,
        "is_enabled": source.is_enabled,
        "mode": source.mode,
        "interval_seconds": source.interval_seconds,
        "timeout_seconds": source.timeout_seconds,
        "stale_after_seconds": source.stale_after_seconds,
        "created_at": _iso_text(source.created_at),
        "updated_at": _iso_text(source.updated_at),
        "pull_token_env_name": pull_token_env_name(source.project_id, source.source_id) if is_pull_used else None,
        "push_token_env_name": event_token_env_name(source.project_id) if is_push_used else None,
        "is_pull_token_configured": is_pull_configured,
        "is_push_token_configured": is_push_configured,
        "is_token_configured": is_pull_configured is not False and is_push_configured is not False,
        "is_failing": is_failing_source(source, state),
        "item_count": len(viewed_items),
        "open_item_count": sum(1 for item in viewed_items if item.is_open and not item.effective.is_hidden),
        "state": _state_entry(state),
    }


def build_source_items(store, source: AttentionSource, source_entry: dict) -> dict:
    """소스 상세: 소스 정보 + 항목마다 앱 값·덮어쓰기·유효 값 (빠진 항목 포함, is_missing 표시)"""
    return {"source": source_entry,
            "items": [_detail_item_entry(item) for item in view_source_items(store, source, is_missing_included=True)]}


def override_entry(override: AttentionItemOverride | None) -> dict:
    override = override or AttentionItemOverride("", "", "")
    return {"is_hidden": override.is_hidden, "label": override.label, "level_policy": override.level_policy,
            "alert_rule": override.alert_rule, "threshold": override.threshold, "channel_kind": override.channel_kind}


def _state_entry(state: AttentionSourceState | None) -> dict | None:
    if state is None:
        return None
    return {
        "last_attempt_at": _iso_text(state.last_attempt_at), "last_success_at": _iso_text(state.last_success_at),
        "last_result": state.last_result, "last_error": state.last_error,
        "consecutive_failures": state.consecutive_failures, "last_generated_at": _iso_text(state.last_generated_at),
        "app": state.app, "app_version": state.app_version, "environment": state.environment,
        "is_baseline_done": state.is_baseline_done, "failure_alerted_at": _iso_text(state.failure_alerted_at),
        "next_due_at": _iso_text(state.next_due_at),
    }


def _board_source_entry(source: AttentionSource, state: AttentionSourceState | None) -> dict:
    return {"source_id": source.source_id, "mode": source.mode,
            "last_result": state.last_result if state is not None else None,
            "last_error": state.last_error if state is not None else None,
            "last_success_at": _iso_text(state.last_success_at) if state is not None else None,
            "is_failing": is_failing_source(source, state)}


def _value_fields(stored: StoredAttentionItem) -> dict:
    """앱이 보낸 값 칸 (kind별로 쓰는 칸만 값이 있음)"""
    return {"group": stored.group, "description": stored.description, "admin_url": stored.admin_url,
            "latest_at": _iso_text(stored.latest_at), "detail": stored.detail, "count": stored.count,
            "total": stored.total, "value": stored.value, "limit": stored.limit, "unit": stored.unit,
            "state": stored.state}


def _board_item_entry(item: ViewedItem) -> dict:
    return {"source_id": item.stored.source_id, "key": item.stored.key, "kind": item.stored.kind,
            "label": item.effective.label, "level": item.effective.level, **_value_fields(item.stored),
            "threshold": item.effective.threshold, "updated_at": _iso_text(item.stored.updated_at),
            "is_open": item.is_open}


def _detail_item_entry(item: ViewedItem) -> dict:
    effective = item.effective
    return {
        "key": item.stored.key, "kind": item.stored.kind,
        "app": {"label": item.stored.label, "level": item.stored.level, **_value_fields(item.stored)},
        "override": override_entry(item.override),
        "effective": {"label": effective.label, "level": effective.level, "rule": effective.rule,
                      "threshold": effective.threshold, "channel_kind": effective.channel_kind,
                      "is_hidden": effective.is_hidden, "is_open": item.is_open},
        "first_seen_at": _iso_text(item.stored.first_seen_at), "updated_at": _iso_text(item.stored.updated_at),
        "is_missing": item.stored.missing_since is not None, "missing_since": _iso_text(item.stored.missing_since),
    }


def _iso_text(moment) -> str | None:
    return moment.isoformat() if moment is not None else None
