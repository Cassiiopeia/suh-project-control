"""관제소 실효 등록 정보 단일 원본: 등록 파일 Registry + 관리자 화면 덮어쓰기 > 실효 Registry
순서: load_registry(파일) > apply_overrides(registry, store) (폴러 재로드·기동 동기화·관리 API 공용)
정렬: 프로젝트·서비스 모두 (sort_order NULL은 맨 뒤, 등록 파일 순서, id), 사용자 추가 항목은 파일 항목 뒤 생성 순"""
from __future__ import annotations

from dataclasses import replace
from typing import Mapping

from service.control_tower.override_models import (
    EMPTY_OVERRIDES, CustomProject, CustomService, ProjectOverride, RegistryOverrides, ServiceOverride,
)
from service.control_tower.registry import CheckSpec, ProjectSpec, Registry, ServiceSpec, load_registry

# 사용자 추가 서비스 기본 부모 (있을 때만)
CUSTOM_SERVICE_DEFAULT_PARENT_ID = "nas"


def load_effective_registry(path: str, environ: Mapping[str, str], store) -> Registry:
    """등록 파일 로드 > 덮어쓰기 적용"""
    return apply_overrides(load_registry(path, environ), store)


def apply_overrides(registry: Registry, store) -> Registry:
    """저장소 덮어쓰기 읽기 > 병합 (store None이면 등록 파일 그대로 정렬만)"""
    overrides = store.load_registry_overrides() if store is not None else EMPTY_OVERRIDES
    return merge_overrides(registry, overrides)


def merge_overrides(registry: Registry, overrides: RegistryOverrides) -> Registry:
    """프로젝트 병합 > 서비스 병합(숨긴 프로젝트 서비스는 비공개) > 인프라 병합 > 상태 페이지"""
    projects = _merge_projects(registry, overrides)
    hidden_project_ids = {project.id for project in projects if project.is_hidden}
    project_ids = {project.id for project in projects}

    registry_service_ids = {service.id for service in registry.services + registry.infrastructure}
    parent_id = CUSTOM_SERVICE_DEFAULT_PARENT_ID if CUSTOM_SERVICE_DEFAULT_PARENT_ID in registry_service_ids else None
    custom_services = [
        _custom_service_spec(custom, parent_id) for custom in overrides.custom_services
        # 등록 파일과 id 충돌·프로젝트 없음 > 제외 (등록 파일 우선)
        if custom.id not in registry_service_ids and custom.project_id in project_ids
    ]
    services = [
        _hide_if_project_hidden(_override_service(service, overrides.service_overrides.get(service.id)),
                                hidden_project_ids)
        for service in list(registry.services) + custom_services
    ]
    infrastructure = [
        _override_service(service, overrides.service_overrides.get(service.id), is_infrastructure=True)
        for service in registry.infrastructure
    ]
    return replace(
        registry,
        projects=tuple(_sorted_by_display_order(projects, _project_sort_order(overrides))),
        services=tuple(_sorted_by_display_order(services, _service_sort_order(overrides))),
        infrastructure=tuple(_sorted_by_display_order(infrastructure, _service_sort_order(overrides))),
        page=overrides.page,
    )


def _merge_projects(registry: Registry, overrides: RegistryOverrides) -> list[ProjectSpec]:
    """등록 파일 프로젝트 + 사용자 추가 프로젝트(id 충돌 제외) > 이름·숨김 덮어쓰기"""
    registry_project_ids = {project.id for project in registry.projects}
    custom_projects = [
        _custom_project_spec(custom, registry) for custom in overrides.custom_projects
        if custom.id not in registry_project_ids
    ]
    return [_override_project(project, overrides.project_overrides.get(project.id))
            for project in list(registry.projects) + custom_projects]


def _custom_project_spec(custom: CustomProject, registry: Registry) -> ProjectSpec:
    """채널 종류·공개 대상은 등록 파일 전역 기본값"""
    return ProjectSpec(custom.id, custom.name, channel_visibility=dict(registry.discord.channel_visibility))


def _custom_service_spec(custom: CustomService, parent_id: str | None) -> ServiceSpec:
    """외부 점검만 있는 서비스"""
    return ServiceSpec(id=custom.id, name=custom.name, project_id=custom.project_id, status=custom.status,
                       is_public=custom.is_public, depends_on=parent_id,
                       external=CheckSpec("http", custom.external_url))


def _override_project(project: ProjectSpec, override: ProjectOverride | None) -> ProjectSpec:
    if override is None:
        return project
    return replace(project,
                   name=override.name if override.name is not None else project.name,
                   is_hidden=override.is_hidden if override.is_hidden is not None else project.is_hidden)


def _override_service(service: ServiceSpec, override: ServiceOverride | None,
                      is_infrastructure: bool = False) -> ServiceSpec:
    """이름·상태 덮어쓰기 (인프라는 공개·외부 주소 덮어쓰기 무시)"""
    if override is None:
        return service
    changes = {}
    if override.name is not None:
        changes["name"] = override.name
    if override.status is not None:
        changes["status"] = override.status
    if not is_infrastructure and override.is_public is not None:
        changes["is_public"] = override.is_public
    if not is_infrastructure and override.external_url is not None:
        changes["external"] = _with_external_url(service.external, override.external_url)
    return replace(service, **changes)


def _with_external_url(external: CheckSpec | None, url: str) -> CheckSpec:
    """기존 외부 점검의 기대 코드·제한 시간 유지, 주소만 교체 (없으면 기본 http 점검)"""
    if external is None:
        return CheckSpec("http", url)
    return replace(external, kind="http", target=url)


def _hide_if_project_hidden(service: ServiceSpec, hidden_project_ids: set[str]) -> ServiceSpec:
    """숨긴 프로젝트 서비스 > 공개 페이지 제외 (감시·알림 유지)"""
    if service.project_id in hidden_project_ids and service.is_public:
        return replace(service, is_public=False)
    return service


def _project_sort_order(overrides: RegistryOverrides) -> dict[str, int]:
    return {project_id: override.sort_order for project_id, override in overrides.project_overrides.items()
            if override.sort_order is not None}


def _service_sort_order(overrides: RegistryOverrides) -> dict[str, int]:
    return {service_id: override.sort_order for service_id, override in overrides.service_overrides.items()
            if override.sort_order is not None}


def _sorted_by_display_order(items: list, sort_order_by_id: dict[str, int]) -> list:
    """(sort_order 없음은 맨 뒤, 원래 순서, id) 정렬"""
    def display_key(indexed_item):
        index, item = indexed_item
        sort_order = sort_order_by_id.get(item.id)
        return (sort_order is None, sort_order or 0, index, item.id)

    return [item for _, item in sorted(enumerate(items), key=display_key)]
