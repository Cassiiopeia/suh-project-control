"""관제소 점검 창 전달: 관리자 화면 점검 창이 Worker 스냅샷·버전까지, 점검 창 안 장애는 공개 장애에서 제외"""
from __future__ import annotations

from datetime import timedelta

from control_tower_poller_fixtures import (  # noqa: F401 (pytest 픽스처 재노출)
    BASE_TIME, NAS_TARGET, FakeHeartbeatClient, check_runner, clock, dispatcher, make_poller, registry_path,
    run_ticks, store,
)
from service.control_tower.poller_steps import build_public_incidents
from service.control_tower.registry import MaintenanceWindow, ProjectSpec, Registry, ServiceSpec

PUBLIC_REGISTRY = Registry(
    projects=(ProjectSpec("elum", "이룸"),),
    services=(ServiceSpec("elum-api", "이룸 API", "elum", is_public=True),
              ServiceSpec("elum-web", "이룸 웹", "elum", is_public=True)),
)


def test_관리자_화면_점검_창이_심박의_점검_창으로_전달된다(registry_path, store, dispatcher, check_runner, clock):
    until = BASE_TIME + timedelta(hours=1)
    store.set_maintenance("elum-api", until, "배포")
    heartbeat_client = FakeHeartbeatClient()

    run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client), clock, 1)
    store.clear_maintenance("elum-api")
    run_ticks(make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client), clock, 1)

    assert heartbeat_client.maintenance_calls[0] == (MaintenanceWindow("elum-api", until, "배포"),)
    assert heartbeat_client.maintenance_calls[1] == ()


def test_등록_파일_스냅샷과_버전은_병합_점검_창을_반영한다():
    registry = Registry(projects=PUBLIC_REGISTRY.projects, services=PUBLIC_REGISTRY.services,
                        maintenance=(MaintenanceWindow("elum-api", BASE_TIME, "등록 파일"),))
    admin_window = MaintenanceWindow("elum-web", BASE_TIME + timedelta(hours=2), "관리자 화면")
    merged = (registry.maintenance[0], admin_window)

    snapshot = registry.to_worker_snapshot(merged)

    assert snapshot["maintenance"] == [
        {"service_id": "elum-api", "until": BASE_TIME.isoformat()},
        {"service_id": "elum-web", "until": (BASE_TIME + timedelta(hours=2)).isoformat()}]
    assert registry.version(merged) != registry.version()
    assert registry.to_worker_snapshot() == registry.to_worker_snapshot(registry.maintenance)


def test_점검_창_안에서_시작하고_끝난_장애는_장애_기록에_표시된다(registry_path, store, dispatcher, check_runner, clock):
    store.set_maintenance("nas", BASE_TIME + timedelta(hours=1), "업데이트")
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock)
    run_ticks(poller, clock, 3)
    check_runner.is_ok_by_target[NAS_TARGET] = True
    run_ticks(poller, clock, 2)

    incidents = store.recent_incidents(10, BASE_TIME - timedelta(days=1))
    assert [(incident["service_id"], incident["is_within_maintenance"]) for incident in incidents] == [("nas", True)]


def test_점검_창이_끝난_뒤_복구된_장애는_점검_창_안이_아니다(registry_path, store, dispatcher, check_runner, clock):
    store.set_maintenance("nas", BASE_TIME + timedelta(minutes=4), "업데이트")
    check_runner.is_ok_by_target[NAS_TARGET] = False
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock)
    run_ticks(poller, clock, 5)
    check_runner.is_ok_by_target[NAS_TARGET] = True
    run_ticks(poller, clock, 2)

    incidents = store.recent_incidents(10, BASE_TIME - timedelta(days=1))
    assert [incident["is_within_maintenance"] for incident in incidents] == [False]


def test_공개_장애는_점검_창_안_장애와_점검_중_진행_장애를_뺀다(store):
    now = BASE_TIME
    # 점검 창 안에서 시작·종료 > 제외
    store.open_incident("elum-api", "service_down", now - timedelta(hours=3), is_in_maintenance=True)
    store.close_incident("elum-api", now - timedelta(hours=2), is_in_maintenance=True)
    # 점검 중 시작했지만 점검 후 종료 > 포함
    store.open_incident("elum-web", "service_down", now - timedelta(hours=5), is_in_maintenance=True)
    store.close_incident("elum-web", now - timedelta(hours=4), is_in_maintenance=False)
    # 진행 중 + 지금 점검 중 > 제외
    store.open_incident("elum-api", "service_down", now - timedelta(minutes=10))
    maintenance = {"elum-api": MaintenanceWindow("elum-api", now + timedelta(hours=1), "")}

    public_incidents = build_public_incidents(PUBLIC_REGISTRY, store, maintenance, now)

    assert [(incident["service_id"], incident["ended_at"] is None) for incident in public_incidents] == [
        ("elum-web", False)]


def test_점검_창이_끝나면_진행_중_장애는_다시_공개된다(store):
    now = BASE_TIME
    store.open_incident("elum-api", "service_down", now - timedelta(minutes=10), is_in_maintenance=True)
    expired = {"elum-api": MaintenanceWindow("elum-api", now - timedelta(minutes=1), "")}

    public_incidents = build_public_incidents(PUBLIC_REGISTRY, store, expired, now)

    assert [incident["service_id"] for incident in public_incidents] == ["elum-api"]


def test_폴러는_등록_파일에_관리자_덮어쓰기를_적용한_실효_등록_정보로_감시한다(registry_path, store, dispatcher,
                                                         check_runner, clock):
    store.save_service_override("elum-admin", {"status": "retired", "name": "이룸 관리자(중지)"}, BASE_TIME)
    heartbeat_client = FakeHeartbeatClient()
    poller = make_poller(registry_path, store, dispatcher, check_runner, clock, heartbeat_client)

    run_ticks(poller, clock, 1)

    assert poller.current_registry().service_by_id("elum-admin").status == "retired"
    assert poller.current_file_registry().service_by_id("elum-admin").status == "active"
    assert "elum-admin" not in poller.snapshot().states
