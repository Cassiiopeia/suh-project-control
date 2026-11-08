"""관제소 등록 파일 로더: 기본값 상속, 환경변수 치환, 검증 오류 수집 (알림 정책·점검 창·스냅샷은 _policies)"""
from __future__ import annotations

import pytest

from config import control_tower_config
from control_tower_registry_fixtures import MINIMAL_REGISTRY, write_registry
from service.control_tower.registry import RegistryError, load_registry

def test_loads_defaults_and_inherits_project(tmp_path):
    registry = load_registry(write_registry(tmp_path, MINIMAL_REGISTRY), {})

    assert registry.alert.failures_to_down == 3
    assert registry.alert.successes_to_up == 2
    assert registry.alert.slow_milliseconds == 5000
    assert registry.alert.reminder_hours == 6
    assert registry.alert.digest_hour_kst == 9
    elum_api = registry.service_by_id("elum-api")
    assert elum_api.project_id == "elum"
    assert elum_api.status == "active"
    assert elum_api.is_public is True
    assert elum_api.external.kind == "http"
    assert elum_api.external.expect == (200,)
    assert elum_api.external.timeout_seconds == 10
    assert registry.projects[0].channel_kinds == ("status", "error", "report", "deploy")
    assert registry.discord.admin_role_name == "관리자"
    assert registry.discord.global_channels["alert"] == ("admin",)


def test_substitutes_env_placeholders(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: elum
            name: 이룸
            services:
              - id: elum-api
                name: 이룸 API
                checks:
                  internal: {url: "http://${NAS_LAN_HOST}:8079/healthz"}
    """)

    registry = load_registry(path, {"NAS_LAN_HOST": "10.0.0.5"})

    assert registry.service_by_id("elum-api").internal.target == "http://10.0.0.5:8079/healthz"


def test_missing_env_placeholder_is_error(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: elum
            name: 이룸
            services:
              - id: elum-api
                name: 이룸 API
                checks:
                  internal: {url: "http://${NAS_LAN_HOST}:8079/healthz"}
    """)

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    assert "NAS_LAN_HOST" in str(raised.value)


def test_rejects_duplicate_ids_unknown_parent_and_bad_status(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: elum
            name: 이룸
            services:
              - id: elum-api
                name: 이룸 API
              - id: elum-api
                name: 이룸 API 복사본
              - id: elum-web
                name: 이룸 웹
                depends_on: ghost-parent
              - id: elum-admin
                name: 이룸 관리자
                status: sleeping
    """)

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    message = str(raised.value)
    assert "duplicate" in message and "elum-api" in message
    assert "ghost-parent" in message
    assert "sleeping" in message


def test_rejects_more_than_45_external_checks(tmp_path):
    service_lines = "".join(
        f"""
      - id: svc-{index}
        name: 서비스 {index}
        checks:
          external: {{url: "https://svc{index}.example.com/"}}"""
        for index in range(control_tower_config.MAX_EXTERNAL_CHECKS + 1)
    )
    path = write_registry(tmp_path, "projects:\n  - id: many\n    name: 많음\n    services:" + service_lines + "\n")

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    assert "external checks" in str(raised.value)
    assert str(control_tower_config.MAX_EXTERNAL_CHECKS) in str(raised.value)


def test_retired_services_do_not_count_toward_external_limit(tmp_path):
    service_lines = "".join(
        f"""
      - id: svc-{index}
        name: 서비스 {index}
        status: retired
        checks:
          external: {{url: "https://svc{index}.example.com/"}}"""
        for index in range(control_tower_config.MAX_EXTERNAL_CHECKS + 1)
    )
    path = write_registry(tmp_path, "projects:\n  - id: many\n    name: 많음\n    services:" + service_lines + "\n")

    assert len(load_registry(path, {}).services) == control_tower_config.MAX_EXTERNAL_CHECKS + 1


def test_project_channel_visibility_overrides_global_default(tmp_path):
    path = write_registry(tmp_path, """
        discord:
          channel_visibility:
            error: [dev]
        projects:
          - id: elum
            name: 이룸
            discord:
              channel_visibility: {error: [member, dev]}
          - id: romrom
            name: 롬롬
    """)

    registry = load_registry(path, {})
    visibility_by_project = {project.id: project.channel_visibility for project in registry.projects}

    assert visibility_by_project["elum"]["error"] == ("member", "dev")
    assert visibility_by_project["romrom"]["error"] == ("dev",)
    assert visibility_by_project["elum"]["status"] == ("member", "dev")
    assert visibility_by_project["romrom"]["report"] == ("dev",)


def test_project_channels_limit_channel_kinds(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: infra
            name: 인프라
            discord:
              channels: [status, error]
    """)

    assert load_registry(path, {}).projects[0].channel_kinds == ("status", "error")


def test_infrastructure_is_separate_and_can_be_parent(tmp_path):
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
              - id: elum-api
                name: 이룸 API
                depends_on: nas
    """)

    registry = load_registry(path, {"NAS_LAN_HOST": "10.0.0.5"})

    nas = registry.service_by_id("nas")
    assert nas in registry.infrastructure
    assert nas.internal.kind == "tcp" and nas.internal.target == "10.0.0.5:5001"
    assert [child.id for child in registry.children_of("nas")] == ["elum-api"]
    assert all(service.id != "nas" for service in registry.services)


def test_rejects_unknown_keys_in_service_project_discord_and_check(tmp_path):
    path = write_registry(tmp_path, """
        discord:
          rolez: {}
        projects:
          - id: elum
            name: 이룸
            colour: red
            discord:
              channelz: [status]
            services:
              - id: elum-api
                name: 이룸 API
                depend_on: nas
                publc: true
                checks:
                  external: {url: "https://a.example.com/", expct: [200]}
        infrastructure:
          - id: nas
            name: NAS
            hostt: x
    """)

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    message = str(raised.value)
    for typo in ("depend_on", "publc", "colour", "channelz", "expct", "hostt", "rolez"):
        assert f"'{typo}'" in message


def test_rejects_dependency_cycles(tmp_path):
    path = write_registry(tmp_path, """
        infrastructure:
          - {id: root, name: 루트}
        projects:
          - id: loop
            name: 순환
            services:
              - {id: svc-x, name: X, depends_on: svc-y}
              - {id: svc-y, name: Y, depends_on: svc-x}
              - {id: svc-ok, name: OK, depends_on: root}
    """)

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    message = str(raised.value)
    assert "cycle" in message and "svc-x" in message and "svc-y" in message
    assert "svc-ok" not in message


def test_unreadable_registry_file_raises_registry_error(tmp_path):
    with pytest.raises(RegistryError) as missing:
        load_registry(str(tmp_path / "nope.yml"), {})
    assert "nope.yml" in str(missing.value)

    broken_path = write_registry(tmp_path, "projects: [unclosed\n  - secret-value\n")
    with pytest.raises(RegistryError) as broken:
        load_registry(broken_path, {})
    assert "services.yml" in str(broken.value) and "line" in str(broken.value)
    assert "secret-value" not in str(broken.value)


def test_rejects_self_dependency_as_cycle(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: loop
            name: 순환
            services:
              - {id: svc-self, name: 자기, depends_on: svc-self}
    """)

    with pytest.raises(RegistryError) as raised:
        load_registry(path, {})

    assert "dependency cycle: svc-self -> svc-self" in str(raised.value)


def test_프로젝트_icon_source_url은_https만_받는다(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: elum
            name: 이룸
            icon_source_url: "https://lab.example.com/elum.png"
          - id: romrom
            name: 롬롬
    """)

    registry = load_registry(path, {})

    assert [project.icon_source_url for project in registry.projects] == ["https://lab.example.com/elum.png", None]


def test_http_icon_source_url은_검증_오류(tmp_path):
    path = write_registry(tmp_path, """
        projects:
          - id: elum
            name: 이룸
            icon_source_url: "http://lab.example.com/elum.png"
    """)

    with pytest.raises(RegistryError) as error:
        load_registry(path, {})

    assert "icon_source_url" in str(error.value)
