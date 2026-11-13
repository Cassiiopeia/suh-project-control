"""관제소 외부 입력 기록용 값 정리 (로그·감사 상세 공용)"""
from __future__ import annotations

# 기록할 최대 글자 수
LOG_VALUE_MAX_LENGTH = 50
# 출력 불가·비ASCII 문자 대체 문자
LOG_VALUE_REPLACEMENT = "?"


def sanitize_log_value(value: str) -> str:
    """로그용 값 정리 (제어문자·비ASCII > ?, 50자 제한)"""
    return "".join(character if character.isprintable() and character.isascii() else LOG_VALUE_REPLACEMENT
                   for character in value[:LOG_VALUE_MAX_LENGTH])
