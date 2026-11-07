"""
관제소 등록 파일 모델: 프로젝트, 서비스, 알림·디스코드 정책, 점검 창, 상태 페이지, Worker 스냅샷
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

# 서비스 생명주기: active 감시·알림·공개 / paused 감시만 / retired 감시 안 함
SERVICE_STATUS_ACTIVE = "active"
SERVICE_STATUS_PAUSED = "paused"
SERVICE_STATUS_RETIRED = "retired"
SERVICE_STATUSES = (SERVICE_STATUS_ACTIVE, SERVICE_STATUS_PAUSED, SERVICE_STATUS_RETIRED)
# 프로젝트 디스코드 채널 종류 (미지정 시 전부)
PROJECT_CHANNEL_KINDS = ("status", "error", "report", "deploy")
# 전역 디스코드 채널 종류
GLOBAL_CHANNEL_KINDS = ("notice", "alert", "digest")
# 채널 공개 대상에 항상 쓸 수 있는 예약 역할 키
RESERVED_ROLE_KEYS = ("admin", "everyone")

DEFAULT_ROLE_NAMES = {"member": "{project}", "dev": "{project}-dev"}
DEFAULT_CHANNEL_NAMES = {
    "status": "상태", "error": "에러", "report": "신고", "deploy": "배포",
    "notice": "공지", "alert": "관제-긴급", "digest": "관제-요약",
}
DEFAULT_CHANNEL_VISIBILITY = {
    "status": ("member", "dev"), "deploy": ("member", "dev"), "error": ("dev",), "report": ("dev",),
}
DEFAULT_GLOBAL_CHANNELS = {"notice": ("everyone",), "alert": ("admin",), "digest": ("admin",)}
# 공개 상태 페이지 기본 제목 / 공지 수준 (info 안내, warning 주의, critical 긴급)
DEFAULT_STATUS_PAGE_TITLE = "SUHSAECHAN Status"
NOTICE_LEVEL_INFO = "info"
NOTICE_LEVELS = (NOTICE_LEVEL_INFO, "warning", "critical")


@dataclass(frozen=True)
class CheckSpec:
    kind: str  # 'http' | 'tcp'
    target: str  # http: URL / tcp: host:port
    expect: tuple[int, ...] = ()  # 비어 있으면 기본 규칙 (502·503·504·520~530·연결 실패 외 정상)
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    name: str
    project_id: str | None  # 인프라 항목은 None
    status: str = SERVICE_STATUS_ACTIVE
    is_public: bool = False
    depends_on: str | None = None
    internal: CheckSpec | None = None
    external: CheckSpec | None = None


@dataclass(frozen=True)
class ProjectSpec:
    id: str
    name: str
    channel_kinds: tuple[str, ...] = PROJECT_CHANNEL_KINDS
    # 채널 종류 > 볼 수 있는 역할 키 (전역 기본값 + 프로젝트 덮어쓰기 반영 완료)
    channel_visibility: dict[str, tuple[str, ...]] = field(default_factory=dict)
    is_hidden: bool = False  # 관리자 화면에서 숨김 > 공개 페이지 제외 (감시·알림은 유지)


@dataclass(frozen=True)
class AlertPolicy:
    failures_to_down: int = 3  # 연속 실패 N회 > down 알림
    successes_to_up: int = 2  # 연속 성공 N회 > 복구 알림
    slow_milliseconds: int = 5000  # 초과 시 degraded
    reminder_hours: int = 6  # down 지속 중 재알림 간격
    digest_hour_kst: int = 9  # 일일 요약 시각 (KST 시)
    parent_recovery_grace_minutes: int = 10  # 부모 복구 후 자식 알림 보류 시간 (분), 이후 계속 down은 묶음 1건
    bulk_alert_threshold: int = 5  # 한 틱 개별 down(또는 복구) 알림이 N건 이상이면 전역 긴급 1건으로 묶음


@dataclass(frozen=True)
class DiscordPolicy:
    role_names: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_ROLE_NAMES))
    admin_role_name: str = "관리자"
    channel_names: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_CHANNEL_NAMES))
    # 전역 채널 종류 > 볼 수 있는 역할 키
    global_channels: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_GLOBAL_CHANNELS))
    # 프로젝트 채널 전역 기본 공개 대상 (프로젝트별 덮어쓰기 전)
    channel_visibility: dict[str, tuple[str, ...]] = field(default_factory=lambda: dict(DEFAULT_CHANNEL_VISIBILITY))


@dataclass(frozen=True)
class MaintenanceWindow:
    service_id: str
    until: datetime  # 시간대 포함
    reason: str = ""

    def is_active_at(self, moment: datetime) -> bool:
        """moment가 점검 창 안인지 (until 직전까지)"""
        return moment < self.until


@dataclass(frozen=True)
class StatusPage:
    title: str = DEFAULT_STATUS_PAGE_TITLE
    notice_text: str = ""  # 빈 문자열이면 공지 없음
    notice_level: str = NOTICE_LEVEL_INFO


@dataclass(frozen=True)
class Registry:
    projects: tuple[ProjectSpec, ...]
    services: tuple[ServiceSpec, ...]
    infrastructure: tuple[ServiceSpec, ...] = ()
    alert: AlertPolicy = field(default_factory=AlertPolicy)
    discord: DiscordPolicy = field(default_factory=DiscordPolicy)
    maintenance: tuple[MaintenanceWindow, ...] = ()
    page: StatusPage = field(default_factory=StatusPage)

    def service_by_id(self, service_id: str) -> ServiceSpec | None:
        """프로젝트 서비스 + 인프라에서 id 조회"""
        for service in self.services + self.infrastructure:
            if service.id == service_id:
                return service
        return None

    def children_of(self, parent_id: str) -> tuple[ServiceSpec, ...]:
        """depends_on이 parent_id인 항목 (서비스 > 인프라 순)"""
        return tuple(
            service for service in self.services + self.infrastructure if service.depends_on == parent_id
        )

    def to_worker_snapshot(self, maintenance: Iterable[MaintenanceWindow] | None = None) -> dict:
        """Worker 전달용 공개 필드만 (내부 점검·의존성·점검 사유 제외, 표시 순서 = 튜플 순서, order 0부터)
        maintenance: 등록 파일 + 관리자 화면 병합 창 (생략 시 등록 파일 창만)"""
        windows = self.maintenance if maintenance is None else tuple(maintenance)
        listed_projects = [project for project in self.projects if not project.is_hidden]
        listed_services = [service for service in self.services if service.status != SERVICE_STATUS_RETIRED]
        return {
            "page": _page_to_snapshot(self.page),
            "alert": {
                "failures_to_down": self.alert.failures_to_down,
                "slow_milliseconds": self.alert.slow_milliseconds,
            },
            "projects": [
                {"id": project.id, "name": project.name, "order": order}
                for order, project in enumerate(listed_projects)
            ],
            "services": [
                _service_to_snapshot(service, order) for order, service in enumerate(listed_services)
            ],
            "maintenance": [
                {"service_id": window.service_id, "until": window.until.isoformat()}
                for window in sorted(windows, key=lambda window: (window.service_id, window.until))
            ],
        }

    def version(self, maintenance: Iterable[MaintenanceWindow] | None = None) -> str:
        """스냅샷 정규화 JSON의 sha256 (변경 감지용, 같은 maintenance 인자로 만든 스냅샷 기준)"""
        canonical_json = json.dumps(
            self.to_worker_snapshot(maintenance), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _page_to_snapshot(page: StatusPage) -> dict:
    """공지 문구 비어 있으면 notice null"""
    notice = {"text": page.notice_text, "level": page.notice_level} if page.notice_text else None
    return {"title": page.title, "notice": notice}


def _service_to_snapshot(service: ServiceSpec, order: int) -> dict:
    external = service.external
    return {
        "id": service.id,
        "order": order,
        "name": service.name,
        "project_id": service.project_id,
        "status": service.status,
        "is_public": service.is_public,
        "external": None if external is None else {
            "url": external.target,
            "expect": list(external.expect),
            "timeout_seconds": external.timeout_seconds,
        },
    }
