"""
관제소 등록 파일 로더: YAML 읽기, ${ENV} 치환, 검증 오류 일괄 수집, Registry 생성
검증 > 파싱 > 참조 검사 (오류는 모아서 RegistryError 1회)
"""
from __future__ import annotations

import re
from dataclasses import fields
from datetime import date, datetime
from typing import Any, Mapping

import yaml

from config import control_tower_config
from service.control_tower.registry_discord_parser import parse_discord, parse_visibility
from service.control_tower.registry_models import (
    PROJECT_CHANNEL_KINDS, RESERVED_ROLE_KEYS, SERVICE_STATUSES,
    AlertPolicy, CheckSpec, DiscordPolicy, MaintenanceWindow, ProjectSpec, Registry, ServiceSpec,
)
from service.control_tower.registry_parse_helpers import (
    as_list, as_mapping, read_positive_int, read_role_keys, read_string,
)

# ${NAME} 환경변수 자리표시자
ENV_PLACEHOLDER_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")
# 최상위에서 허용하는 키
TOP_LEVEL_KEYS = ("alert", "discord", "projects", "infrastructure", "maintenance")
DEFAULT_CHECK_TIMEOUT_SECONDS = 10


class RegistryError(Exception):
    """등록 파일 검증 실패: 메시지에 문제를 줄마다 하나씩 나열"""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("\n".join(self.problems))


def load_registry(path: str, environ: Mapping[str, str]) -> Registry:
    """등록 파일 로드: 읽기 > 환경변수 치환 > 파싱·검증 > Registry"""
    problems: list[str] = []
    with open(path, encoding="utf-8") as registry_file:
        raw_document = yaml.safe_load(registry_file) or {}
    if not isinstance(raw_document, dict):
        raise RegistryError(["registry: top level must be a mapping"])

    document = _substitute_env_placeholders(raw_document, environ, problems, "registry", set())
    for unknown_key in sorted(set(document) - set(TOP_LEVEL_KEYS)):
        problems.append(f"registry: unknown top-level key '{unknown_key}'")

    alert = _parse_alert(document.get("alert"), problems)
    discord = parse_discord(document.get("discord"), problems)
    projects, services = _parse_projects(document.get("projects"), discord, problems)
    infrastructure = tuple(
        _parse_service(raw, None, problems, f"infrastructure[{index}]")
        for index, raw in enumerate(as_list(document.get("infrastructure"), "infrastructure", problems))
    )
    maintenance = _parse_maintenance(document.get("maintenance"), problems)

    _check_references(projects, services, infrastructure, maintenance, problems)
    if problems:
        raise RegistryError(problems)
    return Registry(projects, services, infrastructure, alert, discord, maintenance)


def _substitute_env_placeholders(node: Any, environ: Mapping[str, str], problems: list[str],
                                 where: str, reported_names: set[str]) -> Any:
    """문자열 안 ${NAME} 치환 (없는 변수는 이름별 1회 보고)"""
    if isinstance(node, dict):
        return {key: _substitute_env_placeholders(value, environ, problems, f"{where}.{key}", reported_names)
                for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute_env_placeholders(value, environ, problems, f"{where}[{index}]", reported_names)
                for index, value in enumerate(node)]
    if not isinstance(node, str):
        return node

    def replace_placeholder(match: re.Match) -> str:
        name = match.group(1)
        if name not in environ:
            if name not in reported_names:
                reported_names.add(name)
                problems.append(f"{where}: missing environment variable {name}")
            return match.group(0)
        return environ[name]

    return ENV_PLACEHOLDER_PATTERN.sub(replace_placeholder, node)


def _parse_alert(raw: Any, problems: list[str]) -> AlertPolicy:
    raw_alert = as_mapping(raw, "alert", problems)
    known_keys = {policy_field.name for policy_field in fields(AlertPolicy)}
    for unknown_key in sorted(set(raw_alert) - known_keys):
        problems.append(f"alert: unknown key '{unknown_key}'")
    defaults = AlertPolicy()
    return AlertPolicy(**{
        name: read_positive_int(raw_alert, name, getattr(defaults, name), "alert", problems)
        for name in known_keys
    })


def _parse_projects(raw: Any, discord: DiscordPolicy, problems: list[str]
                    ) -> tuple[tuple[ProjectSpec, ...], tuple[ServiceSpec, ...]]:
    projects: list[ProjectSpec] = []
    services: list[ServiceSpec] = []
    allowed_role_keys = set(discord.role_names) | set(RESERVED_ROLE_KEYS)
    for index, raw_project in enumerate(as_list(raw, "projects", problems)):
        where = f"projects[{index}]"
        raw_project = as_mapping(raw_project, where, problems)
        project_id = read_string(raw_project, "id", where, problems)
        project_name = read_string(raw_project, "name", where, problems) or project_id
        raw_discord = as_mapping(raw_project.get("discord"), f"{where}.discord", problems)

        channel_kinds = _read_channel_kinds(raw_discord.get("channels"), where, problems)
        visibility = {**discord.channel_visibility, **parse_visibility(
            raw_discord.get("channel_visibility"), f"{where}.discord.channel_visibility",
            PROJECT_CHANNEL_KINDS, allowed_role_keys, problems)}
        if project_id:
            projects.append(ProjectSpec(project_id, project_name, channel_kinds, visibility))
        for service_index, raw_service in enumerate(as_list(raw_project.get("services"), f"{where}.services", problems)):
            services.append(_parse_service(raw_service, project_id, problems, f"{where}.services[{service_index}]"))
    return tuple(projects), tuple(services)


def _read_channel_kinds(raw: Any, where: str, problems: list[str]) -> tuple[str, ...]:
    """discord.channels 생략 시 4종 전부"""
    if raw is None:
        return PROJECT_CHANNEL_KINDS
    channel_kinds = read_role_keys(raw, f"{where}.discord.channels", problems)
    for kind in channel_kinds:
        if kind not in PROJECT_CHANNEL_KINDS:
            problems.append(f"{where}.discord.channels: unknown channel kind '{kind}'")
    return channel_kinds


def _parse_service(raw: Any, project_id: str | None, problems: list[str], where: str) -> ServiceSpec:
    raw_service = as_mapping(raw, where, problems)
    service_id = read_string(raw_service, "id", where, problems) or ""
    where = f"{where}({service_id})" if service_id else where
    status = str(raw_service.get("status", "active"))
    if status not in SERVICE_STATUSES:
        problems.append(f"{where}: invalid status '{status}' (allowed: {', '.join(SERVICE_STATUSES)})")
    depends_on = read_string(raw_service, "depends_on", where, problems, False)
    raw_checks = as_mapping(raw_service.get("checks"), f"{where}.checks", problems)
    for unknown_key in sorted(set(raw_checks) - {"external", "internal"}):
        problems.append(f"{where}.checks: unknown key '{unknown_key}'")
    return ServiceSpec(
        id=service_id,
        name=read_string(raw_service, "name", where, problems, False) or service_id,
        project_id=project_id,
        status=status,
        is_public=raw_service.get("public", False) is True,
        depends_on=depends_on,
        internal=_parse_check(raw_checks.get("internal"), f"{where}.checks.internal", False, problems),
        external=_parse_check(raw_checks.get("external"), f"{where}.checks.external", True, problems),
    )


def _parse_check(raw: Any, where: str, is_external: bool, problems: list[str]) -> CheckSpec | None:
    """점검 1건: {url, expect, timeout_seconds} 또는 내부 전용 {tcp: host:port}"""
    if raw is None:
        return None
    raw_check = as_mapping(raw, where, problems)
    timeout_seconds = read_positive_int(raw_check, "timeout_seconds", DEFAULT_CHECK_TIMEOUT_SECONDS, where, problems)
    expect = tuple(as_list(raw_check.get("expect"), f"{where}.expect", problems))
    if not all(isinstance(code, int) and not isinstance(code, bool) for code in expect):
        problems.append(f"{where}: 'expect' must be a list of integer status codes")
        expect = ()

    url, tcp = raw_check.get("url"), raw_check.get("tcp")
    if (url is None) == (tcp is None):
        problems.append(f"{where}: exactly one of 'url' or 'tcp' is required")
        return None
    if tcp is not None:
        if is_external:
            problems.append(f"{where}: external check must use 'url' (tcp is internal only)")
        elif not re.fullmatch(r"[^:\s]+:\d{1,5}", str(tcp)):
            problems.append(f"{where}: 'tcp' must look like host:port")
        return CheckSpec("tcp", str(tcp), expect, timeout_seconds)
    if not re.match(r"https?://\S+$", str(url)):
        problems.append(f"{where}: 'url' must start with http:// or https://")
    return CheckSpec("http", str(url), expect, timeout_seconds)


def _parse_maintenance(raw: Any, problems: list[str]) -> tuple[MaintenanceWindow, ...]:
    windows: list[MaintenanceWindow] = []
    for index, raw_window in enumerate(as_list(raw, "maintenance", problems)):
        where = f"maintenance[{index}]"
        raw_window = as_mapping(raw_window, where, problems)
        service_id = read_string(raw_window, "service", where, problems)
        until = _parse_aware_datetime(raw_window.get("until"), where, problems)
        if service_id and until:
            windows.append(MaintenanceWindow(service_id, until, str(raw_window.get("reason") or "")))
    return tuple(windows)


def _parse_aware_datetime(value: Any, where: str, problems: list[str]) -> datetime | None:
    """ISO8601 > 시간대 포함 datetime (시간대 없으면 오류)"""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            problems.append(f"{where}: 'until' is not a valid ISO8601 datetime")
            return None
    if isinstance(value, date) and not isinstance(value, datetime):
        problems.append(f"{where}: 'until' must include time and timezone offset")
        return None
    if not isinstance(value, datetime):
        problems.append(f"{where}: 'until' is required (ISO8601 with timezone offset)")
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        problems.append(f"{where}: 'until' must include a timezone offset")
        return None
    return value


def _check_references(projects: tuple[ProjectSpec, ...], services: tuple[ServiceSpec, ...],
                      infrastructure: tuple[ServiceSpec, ...], maintenance: tuple[MaintenanceWindow, ...],
                      problems: list[str]) -> None:
    """중복 id, depends_on 대상, 점검 대상, 외부 점검 상한"""
    _report_duplicates([project.id for project in projects], "project", problems)
    every_service = services + infrastructure
    _report_duplicates([service.id for service in every_service], "service", problems)

    known_ids = {service.id for service in every_service}
    for service in every_service:
        if service.depends_on and service.depends_on not in known_ids:
            problems.append(f"service '{service.id}': depends_on unknown parent '{service.depends_on}'")
        if service.depends_on == service.id:
            problems.append(f"service '{service.id}': depends_on itself")
    for window in maintenance:
        if window.service_id not in known_ids:
            problems.append(f"maintenance: unknown service '{window.service_id}'")

    external_count = sum(1 for service in services if service.external and service.status != "retired")
    if external_count > control_tower_config.MAX_EXTERNAL_CHECKS:
        problems.append(f"registry: {external_count} external checks exceed the limit of "
                        f"{control_tower_config.MAX_EXTERNAL_CHECKS}")


def _report_duplicates(identifiers: list[str], label: str, problems: list[str]) -> None:
    seen: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            problems.append(f"{label} '{identifier}': duplicate id")
        seen.add(identifier)
