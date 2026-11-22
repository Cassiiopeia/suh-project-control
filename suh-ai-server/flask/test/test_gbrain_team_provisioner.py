"""GbrainTeamProvisioner: 관리자 토큰(있으면 유지), 설정 파일(개인 임베딩 값 복사·메모리 설정 미복사), gbrain 명령 환경(팀 폴더 고정), nginx map(검사 실패 시 복원), 출력의 DB 비번 가림"""
import json
import subprocess

import pytest

from config import gbrain_server_config
from service.gbrain_instance import build_team_instance
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_provisioner import GbrainTeamProvisioner

DATABASE_PASSWORD = 'secret-pw/with?chars'


@pytest.fixture
def paths(tmp_path, monkeypatch):
    personal_home = tmp_path / 'personal'
    (personal_home / '.gbrain').mkdir(parents=True)
    (personal_home / '.gbrain' / 'config.json').write_text(json.dumps({
        'engine': 'postgres', 'database_url': 'postgresql://gbrain:personal-pw@127.0.0.1:5433/gbrain',
        'embedding_model': 'ollama:qwen3-embedding:0.6b', 'embedding_dimensions': 1024, 'schema_pack': 'gbrain-base-v2',
        'memory': {'auto_writeback': 'salient'},
    }), encoding='utf-8')
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_HOME', str(personal_home))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_BUN_HOME', str(personal_home))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_TEAM_ROOT', str(tmp_path / 'teams'))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_SECRETS_DIR', str(tmp_path / 'secrets'))
    nginx_directory = tmp_path / 'tools' / 'nginx-1.29.3'
    nginx_directory.mkdir(parents=True)
    (nginx_directory / 'nginx.exe').write_text('', encoding='utf-8')
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_NGINX_GLOB', str(tmp_path / 'tools' / 'nginx-*'))
    return tmp_path


@pytest.fixture
def commands(monkeypatch):
    """subprocess.run 캡처: returncode_by_keyword 에 걸리는 명령은 그 코드로 실패"""
    captured = {'calls': [], 'returncode_by_keyword': {}}

    def fake_run(command, **kwargs):
        captured['calls'].append({'command': command, **kwargs})
        returncode = next((code for keyword, code in captured['returncode_by_keyword'].items()
                           if keyword in ' '.join(command)), 0)
        stderr = 'connect postgresql://passql_writer:leaked-pw@127.0.0.1:5433/gbrain_passql failed' if returncode else ''
        return subprocess.CompletedProcess(command, returncode, stdout='', stderr=stderr)
    monkeypatch.setattr(subprocess, 'run', fake_run)
    return captured


def team_instance():
    return build_team_instance('passql', 3141, 'gbrain_passql', 'passql_writer')


def test_관리자_토큰은_없을_때만_만들고_있으면_그대로_둔다(paths):
    provisioner, instance = GbrainTeamProvisioner(), team_instance()

    assert provisioner.ensure_admin_token(instance) is True
    first_token = open(instance.admin_token_file, encoding='ascii').read()
    assert provisioner.ensure_admin_token(instance) is False
    assert open(instance.admin_token_file, encoding='ascii').read() == first_token
    assert len(first_token) >= 32 and '\n' not in first_token


def test_DB_주소는_개인_브레인과_같은_호스트_포트에_쓰기_계정_비번을_인코딩한다(paths):
    database_url = GbrainTeamProvisioner().build_database_url(team_instance(), DATABASE_PASSWORD)

    assert database_url == 'postgresql://passql_writer:secret-pw%2Fwith%3Fchars@127.0.0.1:5433/gbrain_passql'


def test_기존_브레인_설정은_임베딩_값만_옮기고_개인_메모리_설정은_옮기지_않고_마이그레이션만_한다(paths, commands):
    provisioner, instance = GbrainTeamProvisioner(), team_instance()

    provisioner.write_brain_config(instance, 'postgresql://passql_writer:x@127.0.0.1:5433/gbrain_passql')

    written = json.loads(open(gbrain_server_config.get_gbrain_config_path(instance.gbrain_home), encoding='utf-8').read())
    assert written == {'engine': 'postgres', 'database_url': 'postgresql://passql_writer:x@127.0.0.1:5433/gbrain_passql',
                       'embedding_model': 'ollama:qwen3-embedding:0.6b', 'embedding_dimensions': 1024,
                       'schema_pack': 'gbrain-base-v2'}
    gbrain_call = commands['calls'][-1]
    assert gbrain_call['command'][-2:] == ['init', '--migrate-only']
    # 팀 폴더를 GBRAIN_HOME·HOME 으로 고정 > 개인 ~/.gbrain 을 건드리지 않음
    assert gbrain_call['env']['GBRAIN_HOME'] == gbrain_call['env']['HOME'] == instance.gbrain_home


def test_새_브레인은_gbrain_init_에_개인과_같은_임베딩_모델을_넘긴다(paths, commands):
    GbrainTeamProvisioner().initialize_new_brain(team_instance(), 'postgresql://romrom_writer:x@127.0.0.1:5433/gbrain_romrom')

    command = commands['calls'][-1]['command']
    assert command[2:6] == ['init', '--url', 'postgresql://romrom_writer:x@127.0.0.1:5433/gbrain_romrom', '--non-interactive']
    assert command[command.index('--embedding-model') + 1] == 'ollama:qwen3-embedding:0.6b'
    assert command[command.index('--embedding-dimensions') + 1] == '1024'


def test_gbrain_명령_실패_사유에서_DB_비번을_가린다(paths, commands):
    commands['returncode_by_keyword']['--migrate-only'] = 1

    with pytest.raises(GbrainServerError) as error_info:
        GbrainTeamProvisioner().write_brain_config(team_instance(), 'postgresql://passql_writer:x@127.0.0.1:5433/db')

    assert error_info.value.code == 'gbrain_migrate_failed'
    assert 'leaked-pw' not in str(error_info.value) and 'passql_writer:***@' in str(error_info.value)


def test_서비스_설치는_설치_스크립트에_브레인별_값을_넘긴다(paths, commands):
    GbrainTeamProvisioner().install_service(team_instance())

    command = commands['calls'][-1]['command']
    assert command[0] == 'powershell' and '-SkipInstall' in command
    parameters = dict(zip(command[::1], command[1::1]))
    assert parameters['-ServiceName'] == 'gbrain-team-passql' and parameters['-Port'] == '3141'
    assert parameters['-BunHome'] == gbrain_server_config.GBRAIN_BUN_HOME


def test_nginx_map_은_쓰고_검사_후_reload_하고_같은_내용이면_건너뛴다(paths, commands):
    provisioner, instance = GbrainTeamProvisioner(), team_instance()

    assert provisioner.publish_nginx_route(instance) is True
    assert open(provisioner.get_nginx_map_path(instance), encoding='ascii').read() == 'passql 127.0.0.1:3141;\n'
    assert [call['command'][1:] for call in commands['calls']] == [['-t'], ['-s', 'reload']]
    assert provisioner.publish_nginx_route(instance) is False


def test_nginx_검사가_실패하면_새_map_파일을_지워_기존_설정을_유지한다(paths, commands):
    provisioner, instance = GbrainTeamProvisioner(), team_instance()
    commands['returncode_by_keyword']['-t'] = 1

    with pytest.raises(GbrainServerError) as error_info:
        provisioner.publish_nginx_route(instance)

    assert error_info.value.code == 'nginx_test_failed'
    assert not (paths / 'teams' / 'nginx' / 'passql.map').exists()
    assert not any(call['command'][1:] == ['-s', 'reload'] for call in commands['calls'])
