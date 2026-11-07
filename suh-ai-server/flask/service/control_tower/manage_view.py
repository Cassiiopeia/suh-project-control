"""관제소 서비스 관리 화면 조립: 실효 등록 정보(요청 시점 저장소 기준) + 원본·덮어쓰기 구분 > JSON dict
목록(manage)은 외부 주소만, 상세(service detail)는 내부 점검 대상까지 (관리자 전용)"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from config.control_tower_config import MAX_EXTERNAL_CHECKS
from service.control_tower.bootstrap import DEFAULT_STATUS_PAGE_URL, STATUS_PAGE_URL_ENV
from service.control_tower.override_models import RegistryOverrides
from service.control_tower.overview import check_entry, incident_entry, iso_text
from service.control_tower.registry import SERVICE_STATUS_RETIRED, CheckSpec, Registry, ServiceSpec
from service.control_tower.registry_overrides import merge_overrides
from service.control_tower.state_machine import STATUS_UNKNOWN

SOURCE_REGISTRY = "registry"
SOURCE_CUSTOM = "custom"
# 상세 화면: 최근 장애 건수 / 일별 가동률 일수
DETAIL_INCIDENT_LIMIT = 10
DETAIL_UPTIME_DAYS = 30
PERCENT = 100


@dataclass(frozen=True)
class ManageContext:
    file_registry: Registry  # 덮어쓰기 전 등록 파일
    overrides: RegistryOverrides
    effective: Registry  # 등록 파일 + 덮어쓰기 (지금 저장소 기준)

    @property
    def custom_service_ids(self) -> set[str]:
        return {service.id for service in self.overrides.custom_services}

    def is_registry_service(self, service_id: str) -> bool:
        return self.file_registry.service_by_id(service_id) is not None

    def is_known_service(self, service_id: str) -> bool:
        return self.is_registry_service(service_id) or service_id in self.custom_service_ids

    def is_known_project(self, project_id: str) -> bool:
        return any(project.id == project_id for project in self.effective.projects)


def load_manage_context(runtime) -> ManageContext:
    """등록 파일 원본 + 저장소 덮어쓰기 > 실효 등록 정보 (폴러 다음 틱 전에도 화면은 바로 반영)"""
    provider = runtime.file_registry_provider or runtime.registry_provider
    file_registry = provider()
    overrides = runtime.store.load_registry_overrides()
    return ManageContext(file_registry, overrides, merge_overrides(file_registry, overrides))


def count_external_checks(registry: Registry) -> int:
    """Worker 외부 점검 대상 수 (프로젝트 서비스 중 retired 제외, 등록 파일 검사와 같은 기준)"""
    return sum(1 for service in registry.services if service.external and service.status != SERVICE_STATUS_RETIRED)


def build_manage(runtime, context: ManageContext) -> dict:
    """관리 화면 본문: 상태 페이지 설정 > 프로젝트 > 서비스(인프라 포함, 표시 순서) > 외부 점검 사용량"""
    states = _current_states(runtime)
    page = context.effective.page
    invites = runtime.store.all_project_invites()
    return {
        "page": {"title": page.title, "notice_text": page.notice_text, "notice_level": page.notice_level,
                 "preview_url": os.environ.get(STATUS_PAGE_URL_ENV) or DEFAULT_STATUS_PAGE_URL},
        "projects": [_project_entry(project, context, invites.get(project.id))
                     for project in context.effective.projects],
        "services": [_service_entry(service, context, states)
                     for service in context.effective.services + context.effective.infrastructure],
        "external_checks": {"used": count_external_checks(context.effective), "maximum": MAX_EXTERNAL_CHECKS},
    }


def build_service_detail(runtime, context: ManageContext, service_id: str, now: datetime) -> dict | None:
    """정보 창 본문: 관리 항목 + 점검 대상(내부 포함) + 현재 상태·최근 점검 + 최근 장애 10건 + 30일 일별 가동률"""
    service = context.effective.service_by_id(service_id)
    if service is None:
        return None
    snapshot = runtime.poller.snapshot() if runtime.poller is not None else None
    state = snapshot.states.get(service_id) if snapshot is not None else None
    observation = snapshot.observations.get(service_id) if snapshot is not None else None
    is_external_known = observation is not None and observation.is_external_known
    return {
        **_service_entry(service, context, _current_states(runtime)),
        "depends_on": service.depends_on,
        "checks": {"internal": _check_spec_entry(service.internal), "external": _check_spec_entry(service.external)},
        "state": {"status": state.status if state else STATUS_UNKNOWN, "cause": state.cause if state else None,
                  "since": iso_text(state.since) if state else None},
        "last_checks": {"internal": check_entry(observation.internal if observation else None),
                        "external": check_entry(observation.external if is_external_known else None)},
        "incidents": [incident_entry(incident) for incident in
                      runtime.store.recent_incidents_of_service(service_id, DETAIL_INCIDENT_LIMIT)],
        "uptime_days": [_uptime_entry(day, total, ok)
                        for day, total, ok in runtime.store.uptime_by_day(service_id, DETAIL_UPTIME_DAYS)],
    }


def _current_states(runtime) -> dict:
    snapshot = runtime.poller.snapshot() if runtime.poller is not None else None
    return dict(snapshot.states) if snapshot is not None else {}


def _project_entry(project, context: ManageContext, invite=None) -> dict:
    """invite_url: 디스코드 초대 링크 (없으면 null)"""
    override = context.overrides.project_overrides.get(project.id)
    original = next((item for item in context.file_registry.projects if item.id == project.id), None)
    custom = next((item for item in context.overrides.custom_projects if item.id == project.id), None)
    return {
        "id": project.id, "name": project.name, "is_hidden": project.is_hidden,
        "sort_order": override.sort_order if override else None,
        "source": SOURCE_REGISTRY if original is not None else SOURCE_CUSTOM,
        "original_name": original.name if original is not None else (custom.name if custom else project.name),
        "overridden_fields": override.overridden_fields() if override else [],
        "invite_url": invite.url if invite is not None else None,
    }


def _service_entry(service: ServiceSpec, context: ManageContext, states: dict) -> dict:
    """is_public = 서비스 자체 공개 설정, is_listed_publicly = 숨긴 프로젝트 반영 실제 공개 여부"""
    override = context.overrides.service_overrides.get(service.id)
    original = _original_service(service.id, context)
    is_public_setting = override.is_public if override and override.is_public is not None else original.is_public
    state = states.get(service.id)
    return {
        "id": service.id, "name": service.name, "project_id": service.project_id,
        "is_infrastructure": service.project_id is None,
        "source": SOURCE_REGISTRY if context.is_registry_service(service.id) else SOURCE_CUSTOM,
        "status": service.status,
        "is_public": is_public_setting,
        "is_listed_publicly": service.is_public and service.status != SERVICE_STATUS_RETIRED,
        "sort_order": override.sort_order if override else None,
        "url": service.external.target if service.external is not None else None,
        "has_internal_check": service.internal is not None,
        "runtime_status": state.status if state is not None else STATUS_UNKNOWN,
        "overridden_fields": override.overridden_fields() if override else [],
        "original": {"name": original.name, "status": original.status, "is_public": original.is_public,
                     "url": original.external.target if original.external is not None else None},
    }


def _original_service(service_id: str, context: ManageContext) -> ServiceSpec:
    """덮어쓰기 전 값: 등록 파일 서비스 또는 사용자 추가 원본"""
    original = context.file_registry.service_by_id(service_id)
    if original is not None:
        return original
    custom = next(item for item in context.overrides.custom_services if item.id == service_id)
    return ServiceSpec(custom.id, custom.name, custom.project_id, custom.status, custom.is_public,
                       external=CheckSpec("http", custom.external_url))


def _check_spec_entry(check: CheckSpec | None) -> dict | None:
    if check is None:
        return None
    return {"kind": check.kind, "target": check.target, "expect": list(check.expect),
            "timeout_seconds": check.timeout_seconds}


def _uptime_entry(day: str, total: int, ok: int) -> dict:
    """KST 일자 1개 가동률 (데이터 없으면 percent null)"""
    return {"day": day, "total": total, "ok": ok, "percent": round(ok * PERCENT / total, 2) if total else None}
