"""팀 브레인 만들기 #226: 이미 있는 DB 받아 쓰기·손보기, 알 수 없는 DB 거부, 계정 관리 확인, 단계별 실패 응답, dry_run 무변경"""
import os

import pytest

from config import gbrain_server_config
from service.ai_db.ai_db_errors import AiDbUnavailable, GbrainOpsMissing
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_brain_service import GbrainTeamBrainService
from service.gbrain_team_database_steps import classify_team_database
from service.gbrain_team_registry import GbrainTeamRegistry

from gbrain_team_fakes import (
    ADMIN_ROLE, GIVEN_PASSWORD, FakeDatabaseRepair, FakeProvisioner, FakeServerService, FakeTeamAiDbService,
    build_database, build_gbrain_database, build_managed_role,
)


@pytest.fixture
def team_root(tmp_path, monkeypatch):
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_TEAM_ROOT', str(tmp_path))
    monkeypatch.setattr(gbrain_server_config, 'GBRAIN_SECRETS_DIR', str(tmp_path / 'secrets'))
    FakeServerService.installed_services = set()
    return tmp_path


def build_service(ai_db_service, provisioner=None, repair=None):
    return GbrainTeamBrainService(ai_db_service_factory=lambda: ai_db_service, registry=GbrainTeamRegistry(),
                                  provisioner=provisioner or FakeProvisioner(), server_service_factory=FakeServerService,
                                  database_repair=repair or FakeDatabaseRepair(ai_db_service))


# ---------- 판정 ----------
@pytest.mark.parametrize('inspection,expected', [
    ({'exists': False}, 'absent'),
    (build_database(), 'empty'),
    (build_gbrain_database('elum_writer'), 'gbrain'),
    (build_database(public_relation_count=3, foreign_relation_owners=['shop_app']), 'unknown'),
    (build_database(extra_schemas=['shop']), 'unknown'),
    (build_database(foreign_function_count=1), 'unknown'),
    (build_database(can_connect=False), 'unknown'),
])
def test_DB_판정은_쓰기_계정_것이_아닌_객체가_하나라도_있으면_알_수_없음이다(inspection, expected):
    assert classify_team_database(inspection) == expected


# ---------- 이미 있는 DB 받아 쓰기 ----------
def test_이미_있는_빈_DB_는_지우지_않고_받아_써서_권한과_준비를_적용한다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_elum': build_database()})

    created = build_service(ai_db_service).create_team_brain('elum')

    assert created['steps']['database'] == 'adopted' and 'database_repair' not in created['steps']
    assert not any(call[0] == 'create_team_database' for call in ai_db_service.calls)
    assert ('apply_team_writer_grants', 'gbrain_elum', 'elum_writer') in ai_db_service.calls
    assert ('prepare_gbrain', 'gbrain_elum', 'elum_writer') in ai_db_service.calls
    assert created['steps']['config'] == 'initialized'


def test_관리_계정이_못_보는_빈_DB_는_슈퍼유저로_보고_소유자와_준비_함수를_손본_뒤_받아_쓴다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_elum': build_database(owner='gbrain', can_connect=False)})
    repair = FakeDatabaseRepair(ai_db_service,
                                superuser_inspection=build_database(owner='gbrain', has_ops_schema=False))

    created = build_service(ai_db_service, repair=repair).create_team_brain('elum')

    assert repair.calls == [('inspect', 'gbrain_elum'),
                            ('repair', 'gbrain_elum', ADMIN_ROLE, ('owner_changed', 'ops_installed'))]
    assert created['steps']['database'] == 'adopted'
    assert created['steps']['database_repair'] == 'owner_changed+ops_installed'
    assert created['steps']['grants'] == 'reapplied'


def test_기존_계정이_다시_만든_DB_에서_권한을_잃어도_다시_실행하면_권한을_다시_준다(team_root):
    # elum 사례: DB 는 빈 채로 있고 계정만 남음 > 계정 비번은 그대로, 접속 권한은 다시
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_elum': build_database()},
                                        roles={'elum_writer': build_managed_role()})

    created = build_service(ai_db_service).create_team_brain('elum', GIVEN_PASSWORD)

    assert created['steps']['writer_role'] == 'kept' and 'writer_secret' not in created
    assert ('apply_team_writer_grants', 'gbrain_elum', 'elum_writer') in ai_db_service.calls
    grant_index = ai_db_service.calls.index(('apply_team_writer_grants', 'gbrain_elum', 'elum_writer'))
    prepare_index = ai_db_service.calls.index(('prepare_gbrain', 'gbrain_elum', 'elum_writer'))
    assert grant_index < prepare_index


# ---------- 거부 (아무것도 바꾸지 않음) ----------
def test_알_수_없는_객체가_있는_DB_는_아무것도_바꾸지_않고_멈추고_찾은_것을_알린다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_shop': build_database(
        public_relation_count=2, foreign_relation_owners=['shop_app'])})
    provisioner = FakeProvisioner()

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service, provisioner).create_team_brain('shop')

    error = error_info.value
    assert (error.code, error.status_code) == ('team_database_not_empty_unknown', 409)
    assert error.details['found']['foreign_relation_owners'] == ['shop_app']
    assert error.details['steps'] == {} and error.details['failed_step'] == 'database'
    assert '지우지 않았어요' in error.details['next_step']
    assert ai_db_service.mutating_calls() == [] and provisioner.calls == []
    assert not os.path.exists(team_root / 'team-brains.json')


@pytest.mark.parametrize('role,expected_code', [
    ({'exists': True, 'can_login': True, 'is_superuser': False, 'is_managed': False}, 'team_writer_role_not_managed'),
    ({'exists': True, 'can_login': False, 'is_superuser': False, 'is_managed': True}, 'team_writer_role_cannot_login'),
    ({'exists': True, 'can_login': True, 'is_superuser': True, 'is_managed': False}, 'team_writer_role_protected'),
])
def test_관리할_수_없는_쓰기_계정은_바꾸지_않고_멈춘다(team_root, role, expected_code):
    ai_db_service = FakeTeamAiDbService(roles={'romrom_writer': role})

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service).create_team_brain('romrom')

    assert error_info.value.code == expected_code and error_info.value.details['next_step']
    assert ai_db_service.mutating_calls() == []


def test_슈퍼유저_접속을_못_하면_손보기_없이_멈춘다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_elum': build_database(owner='gbrain', can_connect=False)})
    unavailable = GbrainServerError('슈퍼유저 접속 정보 없음', 'team_database_repair_unavailable', 409)
    repair = FakeDatabaseRepair(ai_db_service, error=unavailable)

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service, repair=repair).create_team_brain('elum')

    assert error_info.value.code == 'team_database_repair_unavailable'
    assert ai_db_service.mutating_calls() == []


# ---------- 단계별 실패 응답 모양 ----------
@pytest.mark.parametrize('fail_on,expected_code,expected_step,expected_cause', [
    ({'apply_team_writer_grants': AiDbUnavailable()}, 'ai_db_unavailable', 'grants', 'ai_db_unavailable'),
    ({'apply_team_writer_grants': GbrainOpsMissing()}, 'team_grant_failed', 'grants', 'gbrain_ops_missing'),
    ({'prepare_gbrain': GbrainOpsMissing()}, 'team_prepare_failed', 'prepare', 'gbrain_ops_missing'),
    ({'create_team_writer_role': GbrainOpsMissing()}, 'team_writer_role_create_failed', 'writer_role',
     'gbrain_ops_missing'),
])
def test_DB_단계_실패는_단계_코드_원인_다음_할_일_끝난_단계를_싣는다(team_root, fail_on, expected_code, expected_step,
                                                     expected_cause):
    ai_db_service = FakeTeamAiDbService(fail_on=fail_on)

    with pytest.raises(GbrainServerError) as error_info:
        build_service(ai_db_service).create_team_brain('romrom')

    details = error_info.value.details
    assert (error_info.value.code, details['failed_step'], details['cause']) == (
        expected_code, expected_step, expected_cause)
    assert details['steps']['database'] == 'created' and details['next_step']


@pytest.mark.parametrize('fail_step,expected_code', [
    ('config', 'gbrain_init_failed'), ('service', 'service_install_failed'), ('nginx', 'nginx_test_failed'),
])
def test_서버_단계_실패도_같은_응답_모양이다(team_root, fail_step, expected_code):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), FakeProvisioner(fail_step=fail_step)).create_team_brain('romrom')

    details = error_info.value.details
    assert (error_info.value.code, details['failed_step']) == (expected_code, fail_step)
    assert details['steps']['grants'] == 'reapplied' and details['next_step'] and details['writer_secret']


def test_예상하지_못한_오류도_코드_단계_다음_할_일을_싣는다(team_root):
    provisioner = FakeProvisioner()

    def explode(instance):
        raise PermissionError('denied')
    provisioner.ensure_admin_token = explode

    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService(), provisioner).create_team_brain('romrom')

    details = error_info.value.details
    assert (error_info.value.code, details['failed_step']) == ('team_create_unexpected', 'admin_token')
    assert details['steps']['prepare'] == 'prepared' and details['next_step']


# ---------- dry_run ----------
def test_dry_run_은_새_프로젝트에_아무것도_만들지_않고_계획과_포트를_돌려준다(team_root):
    ai_db_service, provisioner = FakeTeamAiDbService(), FakeProvisioner()
    repair = FakeDatabaseRepair(ai_db_service)

    planned = build_service(ai_db_service, provisioner, repair).plan_team_brain('sandboxcheck')

    assert planned['dry_run'] is True and planned['can_create'] is True and planned['blockers'] == []
    assert planned['plan'] == {'database': 'would_create', 'writer_role': 'would_create', 'grants': 'would_regrant',
                               'prepare': 'would_create', 'admin_token': 'would_create', 'config': 'would_create',
                               'service': 'would_create', 'nginx': 'would_create'}
    brain = planned['brain']
    assert (brain['port'], brain['is_registered'], brain['service_name']) == (3141, False, 'gbrain-team-sandboxcheck')
    assert brain['mcp_url'].endswith('/team/sandboxcheck/mcp') and brain['mcp_server_name'] == 'gbrain-sandboxcheck'
    assert (brain['database_name'], brain['writer_role']) == ('gbrain_sandboxcheck', 'sandboxcheck_writer')
    # 변경 없음: DB·계정·권한·손보기·서버 작업·등록부 파일
    assert ai_db_service.mutating_calls() == [] and provisioner.calls == [] and repair.calls == []
    assert not os.path.exists(team_root / 'team-brains.json')


def test_dry_run_은_기존_브레인에서_있는_것과_다시_줄_권한을_보여_준다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_passql': build_gbrain_database('passql_writer')},
                                        roles={'passql_writer': build_managed_role()})
    GbrainTeamRegistry().register('passql', 'gbrain_passql', 'passql_writer')
    FakeServerService.installed_services = {'gbrain-team-passql'}
    provisioner = FakeProvisioner(has_config=True, has_admin_token=True, is_nginx_published=True)

    planned = build_service(ai_db_service, provisioner).plan_team_brain('passql')

    assert planned['plan'] == {'database': 'exists', 'writer_role': 'exists', 'grants': 'would_regrant',
                               'prepare': 'exists', 'admin_token': 'exists', 'config': 'exists',
                               'service': 'exists', 'nginx': 'exists'}
    assert planned['brain']['is_registered'] is True and planned['brain']['port'] == 3141
    assert ai_db_service.mutating_calls() == []


def test_dry_run_은_알_수_없는_DB_와_비번_없는_기존_계정을_refuse_와_막는_이유로_알린다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_shop': build_database(extra_schemas=['shop'])},
                                        roles={'shop_writer': build_managed_role()})

    planned = build_service(ai_db_service).plan_team_brain('shop')

    assert planned['can_create'] is False
    assert planned['plan']['database'] == 'refuse' and planned['plan']['grants'] == 'refuse'
    assert planned['plan']['config'] == 'refuse'
    codes = [blocker['code'] for blocker in planned['blockers']]
    assert codes == ['team_database_not_empty_unknown', 'writer_password_required']
    assert all(blocker['next_step'] and blocker['error'] for blocker in planned['blockers'])
    assert ai_db_service.mutating_calls() == []


def test_dry_run_은_손볼_DB_를_would_adopt_와_손볼_항목으로_알린다(team_root):
    ai_db_service = FakeTeamAiDbService(databases={'gbrain_elum': build_database(owner='gbrain', has_ops_schema=False)})
    repair = FakeDatabaseRepair(ai_db_service)

    planned = build_service(ai_db_service, repair=repair).plan_team_brain('elum')

    assert planned['plan']['database'] == 'would_adopt'
    assert planned['details']['database_repairs'] == ['owner_changed', 'ops_installed']
    assert repair.calls == [] and ai_db_service.mutating_calls() == []


def test_dry_run_검증_실패도_다음_할_일과_빈_단계를_싣는다(team_root):
    with pytest.raises(GbrainServerError) as error_info:
        build_service(FakeTeamAiDbService()).plan_team_brain('Bad-Key')

    assert error_info.value.code == 'invalid_project'
    assert error_info.value.details['steps'] == {} and error_info.value.details['next_step']
