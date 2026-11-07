"""관제소 등록 파일 정책: 점검 창 파싱, Worker 스냅샷·버전(병합 점검 창 포함), 알림 정책 값 검증, 레포 등록 파일 로드"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import pytest

from config import control_tower_config
from control_tower_registry_fixtures import MINIMAL_REGISTRY, write_registry
from service.control_tower.registry import MaintenanceWindow, RegistryError, load_registry

# 레포 등록 파일의 ${NAME} 자리표시자 (주석 제외 값에서만 찾음)
ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
# 자리표시자 공통 더미 값 (문서용 IP, 호스트·URL 어디에 들어가도 유효)
PLACEHOLDER_ENV_VALUE = "192.0.2.10"


def test_rejects_naive_maintenance_time_and_unknown_service(tmp_path):
    path = write_registry(tmp_path, MINIMAL_REGISTRY + """
maintenance:
  - {service: elum-api, until: "2026-11-06T03:00:00", reason: 시간대 없음}
  - {service: ghost-service, until: "2026-11-06T03:00:00+09:00", reason: 없는 서비스}
""")

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    message = str(raised.value)
    assert "timezone" in message
    assert "ghost-service" in message


def test_loads_maintenance_window_with_offset(tmp_path):
    path = write_registry(tmp_path, MINIMAL_REGISTRY + """
maintenance:
  - {service: elum-api, until: "2026-11-06T03:00+09:00", reason: 이전 작업}
""")

    window = load_registry(path, {}).maintenance[0]

    assert window.service_id == "elum-api"
    assert window.until.utcoffset().total_seconds() == 9 * 3600
    assert window.reason == "이전 작업"


def test_worker_snapshot_excludes_internal_checks_and_secrets(tmp_path):
    path = write_registry(tmp_path, """
        infrastructure:
          - id: nas
            name: 시놀로지 NAS
            checks:
              internal: {tcp: "${NAS_LAN_HOST}:5001"}
        projects:
          - id: elum
            name: 이룸
            services:
              - id: elum-web
                name: 이룸 웹
                depends_on: nas
                checks:
                  internal: {url: "http://${NAS_LAN_HOST}:8079/"}
              - id: elum-api
                name: 이룸 API
                public: true
                depends_on: nas
                checks:
                  external: {url: "https://api.elum.suhsaechan.kr/healthz", expect: [200], timeout_seconds: 8}
                  internal: {url: "http://${NAS_LAN_HOST}:8079/healthz"}
              - id: elum-old
                name: 이룸 옛 서비스
                status: retired
                checks:
                  external: {url: "https://old.elum.suhsaechan.kr/"}
        maintenance:
          - {service: elum-api, until: "2026-11-06T03:00+09:00", reason: 비공개 사유}
    """)

    snapshot = load_registry(path, {"NAS_LAN_HOST": "10.0.0.5"}).to_worker_snapshot()

    assert snapshot == {
        "alert": {"failures_to_down": 3, "slow_milliseconds": 5000},
        "projects": [{"id": "elum", "name": "이룸"}],
        "services": [
            {"id": "elum-api", "name": "이룸 API", "project_id": "elum", "status": "active", "is_public": True,
             "external": {"url": "https://api.elum.suhsaechan.kr/healthz", "expect": [200], "timeout_seconds": 8}},
            {"id": "elum-web", "name": "이룸 웹", "project_id": "elum", "status": "active", "is_public": False,
             "external": None},
        ],
        "maintenance": [{"service_id": "elum-api", "until": "2026-11-06T03:00:00+09:00"}],
    }
    serialized = json.dumps(snapshot, ensure_ascii=False)
    assert "10.0.0.5" not in serialized and "internal" not in serialized and "비공개 사유" not in serialized


def test_version_changes_when_snapshot_changes(tmp_path):
    first = load_registry(write_registry(tmp_path, MINIMAL_REGISTRY), {})
    same = load_registry(write_registry(tmp_path, MINIMAL_REGISTRY), {})
    renamed = load_registry(write_registry(tmp_path, MINIMAL_REGISTRY.replace("이룸 API", "이룸 서버")), {})

    assert re.fullmatch(r"[0-9a-f]{64}", first.version())
    assert first.version() == same.version()
    assert first.version() != renamed.version()


def _repository_registry_placeholder_env() -> dict[str, str]:
    """레포 등록 파일이 참조하는 ${NAME} 전부 > 더미 값 (주석 줄 제외)"""
    with open(control_tower_config.REGISTRY_PATH, encoding="utf-8") as registry_file:
        value_text = "\n".join(line.split("#", 1)[0] for line in registry_file)
    return {name: PLACEHOLDER_ENV_VALUE for name in ENV_PLACEHOLDER_PATTERN.findall(value_text)}


def test_repository_registry_file_loads_with_placeholder_env_within_external_limit():
    environ = _repository_registry_placeholder_env()
    assert "NAS_LAN_HOST" in environ

    registry = load_registry(control_tower_config.REGISTRY_PATH, environ)

    assert registry.service_by_id("control-tower-canary").internal.target == "http://127.0.0.1:18080/"
    assert registry.service_by_id("nas").internal.target == f"{PLACEHOLDER_ENV_VALUE}:5001"
    assert registry.service_by_id("elum-api").external.expect == (200,)
    assert {infrastructure.id for infrastructure in registry.infrastructure} == {"nas", "windows", "home-network"}
    paused_service_ids = [service.id for service in registry.services if service.status == "paused"]
    assert len(paused_service_ids) == 12
    external_count = sum(1 for service in registry.services if service.external and service.status != "retired")
    assert 0 < external_count <= control_tower_config.MAX_EXTERNAL_CHECKS
    assert registry.alert.bulk_alert_threshold == 5


def test_repository_registry_keeps_admin_tools_private_until_owner_confirms():
    registry = load_registry(control_tower_config.REGISTRY_PATH, _repository_registry_placeholder_env())

    for service_id in ("suhsaechan-mail", "suhsaechan-chrome", "suhsaechan-file", "suhsaechan-chat",
                       "suhsaechan-note"):
        assert registry.service_by_id(service_id).is_public is False


def test_snapshot_maintenance_argument_replaces_registry_windows(tmp_path):
    registry = load_registry(write_registry(tmp_path, MINIMAL_REGISTRY + """
maintenance:
  - {service: elum-api, until: "2026-11-06T03:00+09:00", reason: 등록 파일}
"""), {})
    admin_until = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
    merged = (MaintenanceWindow("elum-api", admin_until, "관리자 화면"),)

    assert registry.to_worker_snapshot(merged)["maintenance"] == [
        {"service_id": "elum-api", "until": admin_until.isoformat()}]
    assert registry.to_worker_snapshot([])["maintenance"] == []
    assert registry.version(merged) != registry.version()
    assert registry.version(registry.maintenance) == registry.version()


def test_alert_digest_hour_accepts_midnight_and_rejects_out_of_range(tmp_path):
    midnight = load_registry(write_registry(tmp_path, "alert: {digest_hour_kst: 0}\n"), {})
    assert midnight.alert.digest_hour_kst == 0

    for bad_hour in (24, 99, -1):
        with pytest.raises(RegistryError) as raised:
            load_registry(write_registry(tmp_path, f"alert: {{digest_hour_kst: {bad_hour}}}\n"), {})
        assert "digest_hour_kst" in str(raised.value)

    with pytest.raises(RegistryError) as raised:
        load_registry(write_registry(tmp_path, "alert: {failures_to_down: 0}\n"), {})
    assert "failures_to_down" in str(raised.value)


def test_alert_parent_recovery_grace_minutes_default_override_and_rejects_non_positive(tmp_path):
    assert load_registry(write_registry(tmp_path, MINIMAL_REGISTRY), {}).alert.parent_recovery_grace_minutes == 10
    overridden = load_registry(write_registry(tmp_path, "alert: {parent_recovery_grace_minutes: 15}\n"), {})
    assert overridden.alert.parent_recovery_grace_minutes == 15

    with pytest.raises(RegistryError) as raised:
        load_registry(write_registry(tmp_path, "alert: {parent_recovery_grace_minutes: 0}\n"), {})
    assert "parent_recovery_grace_minutes" in str(raised.value)


def test_alert_bulk_alert_threshold_default_override_and_rejects_non_positive(tmp_path):
    assert load_registry(write_registry(tmp_path, MINIMAL_REGISTRY), {}).alert.bulk_alert_threshold == 5
    overridden = load_registry(write_registry(tmp_path, "alert: {bulk_alert_threshold: 8}\n"), {})
    assert overridden.alert.bulk_alert_threshold == 8

    for bad_value in (0, -3, "many"):
        with pytest.raises(RegistryError) as raised:
            load_registry(write_registry(tmp_path, f"alert: {{bulk_alert_threshold: {bad_value}}}\n"), {})
        assert "bulk_alert_threshold" in str(raised.value)
