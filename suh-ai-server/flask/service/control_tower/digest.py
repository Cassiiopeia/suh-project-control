"""관제소 일일 요약: KST 하루 기준 활성 서비스 가동률(100% 미만만) + 그날과 겹친 장애 건수·다운 시간
+ 앱 확인할 일(요약 시점의 열린 항목 수·연동 끊긴 소스, 없으면 섹션 생략)"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from service.control_tower import alert_texts
from service.control_tower.alert_planner import GLOBAL_SCOPE, Notification
from service.control_tower.app_attention_view import collect_project_attention
from service.control_tower.registry import SERVICE_STATUS_ACTIVE, Registry, ServiceSpec
from service.control_tower.time_zones import KST

DIGEST_KIND = "digest"
SEVERITY_INFO = "info"
DAY_FORMAT = "%Y-%m-%d"
PERCENT = 100
ALL_HEALTHY_LINE = "모든 서비스 정상 (100%)"
NO_DATA_LINE = "집계 데이터 없음"
NO_INCIDENT_LINE = "장애 없음"
APP_ATTENTION_HEADER = "앱 확인할 일"


def build_daily_digest(registry: Registry, store, day_kst: date) -> Notification:
    """요약 1건: 활성 서비스 가동률 줄 > 장애 줄 > 앱 확인할 일 섹션 > 전역 digest 알림"""
    day_text = day_kst.strftime(DAY_FORMAT)
    active_services = [
        service for service in registry.infrastructure + registry.services if service.status == SERVICE_STATUS_ACTIVE
    ]
    sections = [
        _uptime_section(active_services, store.rollups_on_day(day_text)),
        _incident_line(active_services, store, day_kst),
    ]
    app_attention_section = _app_attention_section(registry, store)
    if app_attention_section is not None:
        sections.append(app_attention_section)
    body = "\n".join(sections)
    return Notification(GLOBAL_SCOPE, DIGEST_KIND, SEVERITY_INFO, f"[일일 요약] {day_text}", body, (),
                        f"digest:{day_text}")


def _uptime_section(services: list[ServiceSpec], rollup_by_service_id: dict[str, tuple[int, int]]) -> str:
    """100% 미만 서비스 '{이름}: {가동률:.2f}%' 줄 (없으면 정상 문구, 집계 자체가 없으면 데이터 없음)"""
    rollups = [(service, rollup_by_service_id[service.id]) for service in services
               if service.id in rollup_by_service_id]
    if not rollups:
        return NO_DATA_LINE
    degraded_lines = [
        f"{service.name}: {ok * PERCENT / total:.2f}%" for service, (total, ok) in rollups if ok < total
    ]
    return "\n".join(degraded_lines) if degraded_lines else ALL_HEALTHY_LINE


def _incident_line(services: list[ServiceSpec], store, day_kst: date) -> str:
    """그날과 겹친 장애 'N건, 총 다운 시간' (다운 시간은 그날 안으로 자른 합계)"""
    day_start = datetime.combine(day_kst, time.min, tzinfo=KST)
    day_end = day_start + timedelta(days=1)
    active_service_ids = {service.id for service in services}
    incidents = [incident for incident in store.incidents_overlapping(day_start, day_end)
                 if incident["service_id"] in active_service_ids]
    if not incidents:
        return NO_INCIDENT_LINE
    downtime_seconds = sum(
        (min(incident["ended_at"] or day_end, day_end) - max(incident["started_at"], day_start)).total_seconds()
        for incident in incidents
    )
    return f"장애 {len(incidents)}건, 총 다운 시간 {alert_texts.format_duration_korean(downtime_seconds)}"


def _app_attention_section(registry: Registry, store) -> str | None:
    """프로젝트별 '{이름}: 열린 항목 N건, 연동 끊김 {소스 id}' 줄 (둘 다 없는 프로젝트 생략, 전부 없으면 None)"""
    lines = []
    for project in collect_project_attention(store, registry):
        open_item_count = len(project.open_items)
        failing_source_ids = project.failing_source_ids
        if open_item_count == 0 and not failing_source_ids:
            continue
        parts = [f"열린 항목 {open_item_count}건"]
        if failing_source_ids:
            parts.append(f"연동 끊김 {', '.join(failing_source_ids)}")
        lines.append(f"{project.project_name}: {', '.join(parts)}")
    return "\n".join([APP_ATTENTION_HEADER, *lines]) if lines else None
