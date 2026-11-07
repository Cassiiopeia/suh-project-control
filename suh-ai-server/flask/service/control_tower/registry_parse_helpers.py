"""
등록 파일 파싱 공통 도구: 타입 확인 후 문제 목록에 기록, 기본값 반환
"""
from __future__ import annotations

from typing import Any


def as_mapping(value: Any, where: str, problems: list[str]) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        problems.append(f"{where}: must be a mapping")
        return {}
    return value


def as_list(value: Any, where: str, problems: list[str]) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        problems.append(f"{where}: must be a list")
        return []
    return value


def read_string(raw: dict, key: str, where: str, problems: list[str], is_required: bool = True) -> str | None:
    value = raw.get(key)
    if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
        return str(value).strip()
    if is_required or value is not None:
        problems.append(f"{where}: '{key}' must be a non-empty string")
    return None


def report_unknown_keys(raw: dict, allowed_keys: tuple[str, ...] | set[str], where: str, problems: list[str]) -> None:
    """허용 목록 밖 키 기록 (오타가 조용히 무시되는 것 방지)"""
    for unknown_key in sorted(set(raw) - set(allowed_keys), key=str):
        problems.append(f"{where}: unknown key '{unknown_key}'")


def read_int_in_range(raw: dict, key: str, default: int, minimum: int, maximum: int | None,
                      where: str, problems: list[str]) -> int:
    """정수 값 읽기 (minimum 이상, maximum 있으면 이하, 없으면 default)"""
    if key not in raw:
        return default
    value = raw[key]
    is_in_range = isinstance(value, int) and not isinstance(value, bool) and value >= minimum \
        and (maximum is None or value <= maximum)
    if is_in_range:
        return value
    upper_bound = f" and <= {maximum}" if maximum is not None else ""
    problems.append(f"{where}: '{key}' must be an integer >= {minimum}{upper_bound}")
    return default


def read_positive_int(raw: dict, key: str, default: int, where: str, problems: list[str]) -> int:
    return read_int_in_range(raw, key, default, 1, None, where, problems)


def read_role_keys(value: Any, where: str, problems: list[str]) -> tuple[str, ...]:
    role_keys = as_list(value, where, problems)
    if not all(isinstance(role_key, str) for role_key in role_keys):
        problems.append(f"{where}: role keys must be strings")
        return ()
    return tuple(role_keys)
