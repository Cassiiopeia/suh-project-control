"""
관제소 등록 파일 모델: 프로젝트, 서비스, 알림·디스코드 정책, 점검 창, Worker 스냅샷
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime

# 서비스 생명주기: active 감시·알림·공개 / paused 감시만 / retired 감시 안 함
SERVICE_STATUSES = ("active", "paused", "retired")
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


@dataclass(frozen=True)
class CheckSpec:
    kind: str  # 'http' | 'tcp'
    target: str  # http: URL / tcp: host:port
    expect: tuple[int, ...] = ()  # 비어 있으면 기본 규칙 (502·503·504·연결 실패 외 정상)
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    name: str
    project_id: str | None  # 인프라 항목은 None
    status: str = "active"
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


@dataclass(frozen=True)
class AlertPolicy:
    failures_to_down: int = 3  # 연속 실패 N회 > down 알림
    successes_to_up: int = 2  # 연속 성공 N회 > 복구 알림
    slow_milliseconds: int = 5000  # 초과 시 degraded
    reminder_hours: int = 6  # down 지속 중 재알림 간격
    digest_hour_kst: int = 9  # 일일 요약 시각 (KST 시)
    parent_recovery_grace_minutes: int = 10  # 부모 복구 후 자식 알림 보류 시간 (분), 이후 계속 down은 묶음 1건


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


@dataclass(frozen=True)
class Registry:
    projects: tuple[ProjectSpec, ...]
    services: tuple[ServiceSpec, ...]
    infrastructure: tuple[ServiceSpec, ...] = ()
    alert: AlertPolicy = field(default_factory=AlertPolicy)
    discord: DiscordPolicy = field(default_factory=DiscordPolicy)
    maintenance: tuple[MaintenanceWindow, ...] = ()

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

    def to_worker_snapshot(self) -> dict:
        """Worker 전달용 공개 필드만 (내부 점검·의존성·점검 사유 제외, id 정렬)"""
        return {
            "alert": {
                "failures_to_down": self.alert.failures_to_down,
                "slow_milliseconds": self.alert.slow_milliseconds,
            },
            "projects": [
                {"id": project.id, "name": project.name}
                for project in sorted(self.projects, key=lambda project: project.id)
            ],
            "services": [
                _service_to_snapshot(service)
                for service in sorted(self.services, key=lambda service: service.id)
                if service.status != "retired"
            ],
            "maintenance": [
                {"service_id": window.service_id, "until": window.until.isoformat()}
                for window in sorted(self.maintenance, key=lambda window: (window.service_id, window.until))
            ],
        }

    def version(self) -> str:
        """스냅샷 정규화 JSON의 sha256 (변경 감지용)"""
        canonical_json = json.dumps(
            self.to_worker_snapshot(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _service_to_snapshot(service: ServiceSpec) -> dict:
    external = service.external
    return {
        "id": service.id,
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
