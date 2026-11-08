"""관제소 nginx 설정: 키 검사 제외 경로는 이벤트·앱 확인할 일 push 입구 2개, 본문 상한·전용 속도 제한, 공개 경로 map은 정규화 $uri 기준"""
from __future__ import annotations

import os
import re

NGINX_CONF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "nginx.conf")
EVENT_LOCATION = "= /api/flask/control/events"
ATTENTION_LOCATION = "^~ /api/flask/control/attention/"
# 키 검사 제외를 허용하는 location 머리 (이 목록과 정확히 일치해야 함)
ALLOWED_EXEMPT_LOCATIONS = {EVENT_LOCATION, ATTENTION_LOCATION}


def _read_conf() -> str:
    with open(NGINX_CONF_PATH, encoding="utf-8") as conf_file:
        return conf_file.read()


def _location_blocks(conf_text: str) -> dict[str, str]:
    """location 머리 > 본문 (다음 location 전까지)"""
    blocks = re.split(r"\n\s*location\s+", conf_text)[1:]
    return {block.split("{", 1)[0].strip(): block.split("{", 1)[1] for block in blocks}


def _public_endpoint_map(conf_text: str) -> tuple[str, str]:
    """$is_public_endpoint map > (키 변수, 본문)"""
    match = re.search(r"map\s+(\$\w+)\s+\$is_public_endpoint\s*\{(.*?)\}", conf_text, re.DOTALL)
    assert match is not None
    return match.group(1), match.group(2)


def test_nginx_키_검사_제외_경로는_허용_목록과_정확히_일치한다():
    exempt_locations = [location for location, body in _location_blocks(_read_conf()).items()
                        if "return 401" not in body]
    assert len(exempt_locations) == len(ALLOWED_EXEMPT_LOCATIONS)
    assert set(exempt_locations) == ALLOWED_EXEMPT_LOCATIONS


def test_push_입구는_64KB_상한과_이벤트_입구_속도_제한을_쓰고_관리_API는_덮지_않는다():
    attention_block = _location_blocks(_read_conf())[ATTENTION_LOCATION]
    attention_prefix = ATTENTION_LOCATION.split()[1]

    assert re.search(r"client_max_body_size\s+64k;", attention_block)
    assert re.search(r"limit_req\s+zone=control_events\s+burst=10\s+nodelay;", attention_block)
    assert "python_limit" not in attention_block
    assert re.search(r"rewrite\s+\^/api/flask/\(\.\*\)\$\s+/\$1\s+break;", attention_block)
    assert "/api/flask/control/attention/elum/api".startswith(attention_prefix)
    assert not "/api/flask/control/app-attention/sources".startswith(attention_prefix)


def test_event_intake_caps_body_and_uses_dedicated_rate_limit():
    conf_text = _read_conf()
    event_block = _location_blocks(conf_text)[EVENT_LOCATION]

    assert re.search(r"client_max_body_size\s+16k;", event_block)
    assert re.search(r"limit_req\s+zone=control_events\s+burst=10\s+nodelay;", event_block)
    assert "python_limit" not in event_block
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=control_events:1m\s+rate=5r/s;", conf_text)


def test_public_endpoint_map_uses_normalized_uri_and_has_no_control_pattern():
    key_variable, map_body = _public_endpoint_map(_read_conf())

    patterns = [line.split("#", 1)[0].split()[0] for line in map_body.splitlines()
                if line.split("#", 1)[0].strip()]

    assert key_variable == "$uri"
    assert "default" in patterns and len(patterns) > 1
    assert not any("control" in pattern for pattern in patterns)
