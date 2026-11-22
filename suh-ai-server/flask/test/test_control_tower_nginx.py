"""관제소 nginx 설정: 키 검사 제외 경로는 이벤트·앱 확인할 일 push 입구 2개, 본문 상한·전용 속도 제한, 공개 경로 map은 정규화 $uri 기준, 키는 X-API-Key 또는 Bearer, gbrain /admin 은 게이트 쿠키, /mcp 는 gbrain 토큰 + Bearer 필수·속도 제한"""
from __future__ import annotations

import os
import re

NGINX_CONF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "config", "nginx.conf")
EVENT_LOCATION = "= /api/flask/control/events"
ATTENTION_LOCATION = "^~ /api/flask/control/attention/"
# 키 검사 제외를 허용하는 location 머리 (이 목록과 정확히 일치해야 함)
ALLOWED_EXEMPT_LOCATIONS = {EVENT_LOCATION, ATTENTION_LOCATION}
# gbrain 관리자 화면: 키 대신 관제소 게이트 쿠키 (auth_request) 로 막는 location 머리
GBRAIN_ADMIN_LOCATIONS = {"^~ /admin/auth/", "^~ /admin"}
GBRAIN_GATE_LOCATION = "= /_gbrain_admin_gate"
# gbrain 공개 MCP: 정확 경로 하나만 (토큰 검사는 gbrain, nginx 는 Bearer 형식·속도·크기만)
GBRAIN_MCP_LOCATION = "= /mcp"


def _read_conf() -> str:
    with open(NGINX_CONF_PATH, encoding="utf-8") as conf_file:
        return conf_file.read()


def _location_blocks(conf_text: str) -> dict[str, str]:
    """location 머리 > 본문 (다음 location 전까지)"""
    blocks = re.split(r"\n\s*location\s+", conf_text)[1:]
    return {block.split("{", 1)[0].strip(): block.split("{", 1)[1] for block in blocks}


def _map_body(conf_text: str, source_variable: str, result_variable: str) -> str:
    """map <원본> <결과> { 본문 } > 본문 (닫는 괄호는 줄 단독: 키 목록 자리 {{...}} 와 구분)"""
    pattern = r"map\s+" + re.escape(source_variable) + r"\s+" + re.escape(result_variable) + r"\s*\{(.*?)\n\s*\}"
    match = re.search(pattern, conf_text, re.DOTALL)
    assert match is not None, f"map {source_variable} {result_variable} missing"
    return match.group(1)


def _public_endpoint_map(conf_text: str) -> tuple[str, str]:
    """$is_public_endpoint map > (키 변수, 본문)"""
    match = re.search(r"map\s+(\$\w+)\s+\$is_public_endpoint\s*\{(.*?)\}", conf_text, re.DOTALL)
    assert match is not None
    return match.group(1), match.group(2)


def test_nginx_키_검사_제외_경로는_허용_목록과_정확히_일치한다():
    # 내부 전용(internal)·게이트 검사(auth_request) location 은 별도 테스트로 검사
    exempt_locations = [location for location, body in _location_blocks(_read_conf()).items()
                        if "return 401" not in body and "auth_request" not in body
                        and not re.search(r"^\s*internal;", body, re.MULTILINE)]
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

    assert re.search(r"client_max_body_size\s+64k;", event_block)
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


def test_api_키는_X_API_Key_우선_없으면_Bearer_토큰을_같은_키_목록으로_검사한다():
    conf_text = _read_conf()
    bearer_map = _map_body(conf_text, "$http_authorization", "$api_key_bearer")
    candidate_map = _map_body(conf_text, "$http_x_api_key", "$api_key_candidate")
    valid_map = _map_body(conf_text, "$api_key_candidate", "$api_key_valid")

    assert '"~*^Bearer\\s+(?<bearer_token>\\S+)$" $bearer_token;' in bearer_map
    assert re.search(r"default\s+\$http_x_api_key;", candidate_map)
    assert re.search(r'""\s+\$api_key_bearer;', candidate_map)
    # 배포가 치환하는 키 목록 자리는 검사 map 한 곳에만 (기본 거부)
    assert re.search(r"default\s+0;", valid_map) and "{{OLLAMA_API_KEY_LIST}}" in valid_map
    assert conf_text.count("{{OLLAMA_API_KEY_LIST}}") == 1


def test_gbrain_admin_은_게이트_쿠키_검사를_거친다():
    conf_text = _read_conf()
    blocks = _location_blocks(conf_text)
    gated_locations = {location for location, body in blocks.items() if "auth_request" in body}

    assert gated_locations == GBRAIN_ADMIN_LOCATIONS
    for location in GBRAIN_ADMIN_LOCATIONS:
        body = blocks[location]
        assert re.search(r"auth_request\s+/_gbrain_admin_gate;", body)
        assert re.search(r"proxy_pass\s+http://gbrain_backend;", body)
        assert re.search(r"proxy_cookie_flags\s+gbrain_admin\s+secure;", body)
    assert re.search(r"upstream\s+gbrain_backend\s*\{\s*server\s+127\.0\.0\.1:3131;", conf_text)


def test_gbrain_으로_가는_경로는_admin_과_정확한_mcp_뿐이다():
    blocks = _location_blocks(_read_conf())
    gbrain_locations = {location for location, body in blocks.items() if "proxy_pass http://gbrain_backend;" in body}

    # OAuth(/authorize·/token·/register)·/.well-known·/mcp/ 하위 경로는 미노출
    assert gbrain_locations == GBRAIN_ADMIN_LOCATIONS | {GBRAIN_MCP_LOCATION}
    assert not any(keyword in location for location in blocks
                   for keyword in ("well-known", "oauth", "authorize", "token", "register"))


def test_mcp_는_POST_와_Bearer_헤더가_없으면_gbrain_전에_거부한다():
    mcp_block = _location_blocks(_read_conf())[GBRAIN_MCP_LOCATION]

    assert re.search(r"if \(\$request_method != POST\)\s*\{\s*return 405", mcp_block)
    assert 'if ($http_authorization !~* "^Bearer\\s+\\S+$")' in mcp_block
    assert re.search(r"return 401 ", mcp_block)
    # 거부가 프록시보다 먼저
    assert mcp_block.index("return 401") < mcp_block.index("proxy_pass")
    # Ollama 키 검사(관제소 키) 와 섞지 않음
    assert "$api_key_valid" not in mcp_block and "$is_public_endpoint" not in mcp_block


def test_mcp_는_실제_접속_IP_와_전체_상한_두_속도_제한과_본문_상한을_쓴다():
    conf_text = _read_conf()
    mcp_block = _location_blocks(conf_text)[GBRAIN_MCP_LOCATION]
    client_key_map = _map_body(conf_text, "$http_cf_connecting_ip", "$mcp_client_key")

    assert re.search(r"default\s+\$http_cf_connecting_ip;", client_key_map)
    assert re.search(r'""\s+\$binary_remote_addr;', client_key_map)
    assert re.search(r"limit_req_zone\s+\$mcp_client_key\s+zone=mcp_client:10m\s+rate=10r/s;", conf_text)
    assert re.search(r"limit_req_zone\s+\$binary_remote_addr\s+zone=mcp_total:1m\s+rate=30r/s;", conf_text)
    assert re.search(r"limit_req\s+zone=mcp_client\s+burst=\d+\s+nodelay;", mcp_block)
    assert re.search(r"limit_req\s+zone=mcp_total\s+burst=\d+\s+nodelay;", mcp_block)
    assert re.search(r"limit_req_status\s+429;", mcp_block)
    assert re.search(r"client_max_body_size\s+4m;", mcp_block)


def test_mcp_접근_로그는_쿼리와_Authorization_을_남기지_않고_CORS_별표를_물려받지_않는다():
    conf_text = _read_conf()
    mcp_block = _location_blocks(conf_text)[GBRAIN_MCP_LOCATION]
    log_format_match = re.search(r"log_format\s+mcp\s+(.*?);", conf_text, re.DOTALL)

    assert log_format_match is not None
    log_format_text = log_format_match.group(1)
    assert "$uri" in log_format_text
    assert "$request " not in log_format_text and "$request_uri" not in log_format_text and "$args" not in log_format_text
    assert "authorization" not in log_format_text.lower()
    assert "authorization" not in re.search(r"log_format\s+main\s+(.*?);", conf_text, re.DOTALL).group(1).lower()
    assert re.search(r"access_log\s+logs/access\.log\s+mcp;", mcp_block)
    # location 안 add_header 가 server 의 Access-Control-Allow-Origin '*' 상속을 끊음
    assert "add_header" in mcp_block and "Access-Control-Allow-Origin" not in mcp_block


def test_gbrain_게이트는_내부_전용이고_1회용_로그인_경로는_로그를_남기지_않는다():
    blocks = _location_blocks(_read_conf())
    gate_body = blocks[GBRAIN_GATE_LOCATION]

    assert re.search(r"^\s*internal;", gate_body, re.MULTILINE)
    assert re.search(r"proxy_pass\s+http://python_backend/gbrain/admin-gate;", gate_body)
    assert re.search(r"access_log\s+off;", blocks["^~ /admin/auth/"])
    assert "access_log off;" not in blocks["^~ /admin"]


# ---------- gbrain 팀 브레인 (#210) ----------
GBRAIN_TEAM_LOCATION = "~ ^/team/(?<team_brain_project>[a-z][a-z0-9]+)/mcp$"


def test_팀_브레인_경로는_정확한_모양_하나뿐이고_map_파일로만_포트를_찾는다():
    conf_text = _read_conf()
    blocks = _location_blocks(conf_text)
    team_locations = {location for location, body in blocks.items() if "$team_brain_upstream" in body}

    assert team_locations == {GBRAIN_TEAM_LOCATION}
    team_map = _map_body(conf_text, "$team_brain_project", "$team_brain_upstream")
    assert re.search(r'default\s+"";', team_map)
    # 관제소가 쓰는 파일만 포함 (배포 폴더 밖, 0개여도 nginx -t 통과)
    assert re.search(r"include\s+C:/AI/gbrain/teams/nginx/\*\.map;", team_map)
    assert re.search(r"proxy_pass\s+http://\$team_brain_upstream/mcp;", blocks[GBRAIN_TEAM_LOCATION])


def test_팀_브레인_경로는_POST_Bearer_검사와_모르는_프로젝트_404_가_프록시보다_먼저다():
    team_block = _location_blocks(_read_conf())[GBRAIN_TEAM_LOCATION]

    assert re.search(r"if \(\$request_method != POST\)\s*\{\s*return 405", team_block)
    assert 'if ($http_authorization !~* "^Bearer\\s+\\S+$")' in team_block
    assert re.search(r'if \(\$team_brain_upstream = ""\)\s*\{\s*return 404', team_block)
    proxy_position = team_block.index("proxy_pass")
    assert max(team_block.index("return 405"), team_block.index("return 401"), team_block.index("return 404")) < proxy_position
    assert "$api_key_valid" not in team_block and "$is_public_endpoint" not in team_block


def test_팀_브레인_경로는_mcp_와_같은_속도_제한_본문_상한_로그_형식을_쓴다():
    team_block = _location_blocks(_read_conf())[GBRAIN_TEAM_LOCATION]

    assert re.search(r"limit_req\s+zone=mcp_client\s+burst=\d+\s+nodelay;", team_block)
    assert re.search(r"limit_req\s+zone=mcp_total\s+burst=\d+\s+nodelay;", team_block)
    assert re.search(r"limit_req_status\s+429;", team_block)
    assert re.search(r"client_max_body_size\s+4m;", team_block)
    assert re.search(r"access_log\s+logs/access\.log\s+mcp;", team_block)
    assert "add_header" in team_block and "Access-Control-Allow-Origin" not in team_block


def test_팀_브레인은_admin_OAuth_discovery_를_공개하지_않는다():
    blocks = _location_blocks(_read_conf())
    team_headers = [location for location in blocks if "/team" in location]

    assert team_headers == [GBRAIN_TEAM_LOCATION]
    assert not any(keyword in GBRAIN_TEAM_LOCATION for keyword in ("admin", "well-known", "oauth", "token"))
