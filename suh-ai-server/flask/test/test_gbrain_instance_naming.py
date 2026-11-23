"""gbrain 인스턴스 이름 규칙 고정: 개인 1개 + 팀 프로젝트 키 > 서비스·MCP 이름·공개 주소·DB·계정·토큰 파일 (#213 단일 원본)"""
import os

from service.gbrain_instance import build_personal_instance, build_team_instance, to_team_database_name, to_team_writer_role


def test_개인_브레인_이름():
    instance = build_personal_instance()

    assert (instance.service_name, instance.port, instance.mcp_server_name) == ('gbrain-http', 3131, 'gbrain')
    assert instance.mcp_url == 'https://ai.suhsaechan.kr/mcp'
    assert instance.database_name == 'gbrain'
    assert instance.default_scope_preset == 'read_write'


def test_팀_브레인_이름은_프로젝트_키에서_정해진다():
    instance = build_team_instance('passql', 3141, to_team_database_name('passql'), to_team_writer_role('passql'))

    assert instance.service_name == 'gbrain-team-passql'
    assert instance.mcp_server_name == 'gbrain-passql'
    assert instance.mcp_url == 'https://ai.suhsaechan.kr/team/passql/mcp'
    assert (instance.database_name, instance.writer_role) == ('gbrain_passql', 'passql_writer')
    assert instance.admin_token_file.replace(os.sep, '/').endswith('/gbrain-team-passql-admin-token')
    assert instance.log_path.replace(os.sep, '/').endswith('/passql/logs/gbrain-http.log')
    assert instance.default_scope_preset == 'read_only'
