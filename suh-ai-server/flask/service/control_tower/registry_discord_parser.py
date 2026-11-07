"""
등록 파일 discord 섹션 파싱: 역할 이름, 채널 이름, 채널 공개 대상 (기본값 위에 덮어쓰기)
"""
from __future__ import annotations

from typing import Any

from service.control_tower.registry_models import (
    GLOBAL_CHANNEL_KINDS, PROJECT_CHANNEL_KINDS, RESERVED_ROLE_KEYS, DiscordPolicy,
)
from service.control_tower.registry_parse_helpers import as_mapping, read_role_keys, read_string


def parse_discord(raw: Any, problems: list[str]) -> DiscordPolicy:
    """디스코드 정책: 기본값 위에 등록 파일 값을 종류별로 덮어씀"""
    raw_discord = as_mapping(raw, "discord", problems)
    defaults = DiscordPolicy()
    role_names = {**defaults.role_names, **as_mapping(raw_discord.get("roles"), "discord.roles", problems)}
    channel_names = {**defaults.channel_names,
                     **as_mapping(raw_discord.get("channel_names"), "discord.channel_names", problems)}
    admin_role_name = read_string(raw_discord, "admin_role_name", "discord", problems, False) or defaults.admin_role_name

    allowed_role_keys = set(role_names) | set(RESERVED_ROLE_KEYS)
    channel_visibility = dict(defaults.channel_visibility)
    channel_visibility.update(parse_visibility(
        raw_discord.get("channel_visibility"), "discord.channel_visibility", PROJECT_CHANNEL_KINDS,
        allowed_role_keys, problems))
    global_channels = dict(defaults.global_channels)
    for kind, raw_channel in as_mapping(raw_discord.get("global_channels"), "discord.global_channels", problems).items():
        where = f"discord.global_channels.{kind}"
        if kind not in GLOBAL_CHANNEL_KINDS:
            problems.append(f"{where}: unknown global channel kind")
            continue
        role_keys = read_role_keys(as_mapping(raw_channel, where, problems).get("visible_to"), where, problems)
        check_role_keys(role_keys, allowed_role_keys, where, problems)
        global_channels[kind] = role_keys
    return DiscordPolicy(role_names, admin_role_name, channel_names, global_channels, channel_visibility)


def parse_visibility(raw: Any, where: str, allowed_kinds: tuple[str, ...], allowed_role_keys: set[str],
                      problems: list[str]) -> dict[str, tuple[str, ...]]:
    visibility: dict[str, tuple[str, ...]] = {}
    for kind, raw_role_keys in as_mapping(raw, where, problems).items():
        if kind not in allowed_kinds:
            problems.append(f"{where}.{kind}: unknown channel kind")
            continue
        role_keys = read_role_keys(raw_role_keys, f"{where}.{kind}", problems)
        check_role_keys(role_keys, allowed_role_keys, f"{where}.{kind}", problems)
        visibility[kind] = role_keys
    return visibility


def check_role_keys(role_keys: tuple[str, ...], allowed_role_keys: set[str], where: str, problems: list[str]) -> None:
    for role_key in role_keys:
        if role_key not in allowed_role_keys:
            problems.append(f"{where}: unknown role key '{role_key}'")
