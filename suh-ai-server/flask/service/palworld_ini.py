"""
PalWorldSettings.ini OptionSettings 파서/직렬화
OptionSettings=(k=v,k=v,...) 한 줄 포맷 전용. 따옴표 내 콤마를 안전하게 처리한다.
"""
import re
from config.palworld_config import STRING_KEYS

_OPTION_RE = re.compile(r'^(OptionSettings=\()(.*)(\))(\s*)$', re.MULTILINE)


def _split_pairs(inner: str) -> list[str]:
    parts, buf, in_quotes, nested_depth = [], [], False, 0
    for ch in inner:
        if ch == '"':
            in_quotes = not in_quotes
            buf.append(ch)
        elif ch == '(' and not in_quotes:
            nested_depth += 1
            buf.append(ch)
        elif ch == ')' and not in_quotes:
            nested_depth = max(0, nested_depth - 1)
            buf.append(ch)
        elif ch == ',' and not in_quotes and nested_depth == 0:
            parts.append(''.join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append(''.join(buf))
    return parts


def parse_option_settings(text: str) -> dict:
    match = _OPTION_RE.search(text)
    if not match:
        raise ValueError("OptionSettings line not found in ini content")
    result = {}
    for pair in _split_pairs(match.group(2)):
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        result[key.strip()] = value.strip()
    return result


def update_option_settings(text: str, changes: dict) -> str:
    current = parse_option_settings(text)
    for key, value in changes.items():
        value = str(value)
        if '"' in value.strip('"'):
            raise ValueError(f'Value for {key} must not contain double quotes')
        if key in STRING_KEYS and not (value.startswith('"') and value.endswith('"')):
            value = f'"{value}"'
        current[key] = value
    serialized = ','.join(f'{k}={v}' for k, v in current.items())
    def replace_func(m):
        return f'{m.group(1)}{serialized}{m.group(3)}{m.group(4)}'
    return _OPTION_RE.sub(replace_func, text, count=1)
