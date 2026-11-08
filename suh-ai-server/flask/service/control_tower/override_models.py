"""관제소 관리자 화면 덮어쓰기 모델: 서비스·프로젝트 덮어쓰기, 사용자 추가 서비스·프로젝트, 묶음
덮어쓰기 칸 None = 등록 파일(또는 사용자 추가 원본) 값 사용"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from service.control_tower.registry import StatusPage

# 서비스 덮어쓰기 칸 5개 (PATCH 허용 키와 같음)
SERVICE_OVERRIDE_FIELDS = ("name", "status", "is_public", "sort_order", "external_url")
# 프로젝트 덮어쓰기 칸 3개
PROJECT_OVERRIDE_FIELDS = ("name", "is_hidden", "sort_order")


@dataclass(frozen=True)
class ServiceOverride:
    service_id: str
    name: str | None = None
    status: str | None = None  # active 추적함 / paused 감시만 / retired 추적 안 함
    is_public: bool | None = None
    sort_order: int | None = None  # 작을수록 앞, None은 맨 뒤
    external_url: str | None = None
    updated_at: datetime | None = None

    def overridden_fields(self) -> list[str]:
        """값이 있는 덮어쓰기 칸 이름"""
        return [name for name in SERVICE_OVERRIDE_FIELDS if getattr(self, name) is not None]


@dataclass(frozen=True)
class CustomService:
    id: str
    project_id: str
    name: str
    external_url: str
    status: str
    is_public: bool
    sort_order: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ProjectOverride:
    project_id: str
    name: str | None = None
    is_hidden: bool | None = None
    sort_order: int | None = None
    updated_at: datetime | None = None

    def overridden_fields(self) -> list[str]:
        return [name for name in PROJECT_OVERRIDE_FIELDS if getattr(self, name) is not None]


@dataclass(frozen=True)
class CustomProject:
    id: str
    name: str
    sort_order: int | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class RegistryOverrides:
    """저장소에서 한 번에 읽은 덮어쓰기 전체 (사용자 추가 항목은 생성 순)"""
    service_overrides: dict[str, ServiceOverride] = field(default_factory=dict)
    custom_services: tuple[CustomService, ...] = ()
    project_overrides: dict[str, ProjectOverride] = field(default_factory=dict)
    custom_projects: tuple[CustomProject, ...] = ()
    page: StatusPage = field(default_factory=StatusPage)
    project_icon_versions: dict[str, str] = field(default_factory=dict)  # project_id > 썸네일 내용 해시 12자


EMPTY_OVERRIDES = RegistryOverrides()
