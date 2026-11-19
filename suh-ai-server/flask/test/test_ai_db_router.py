"""AI 서버 DB API: 오류 코드·상태, 미설정 503, 비번 1회 응답·감사 상세 제외, 권한 주기·빼기 위임, 감사 카테고리, gbrain"""
from __future__ import annotations

import json
import logging
from unittest.mock import patch

import pytest
from flask import Flask

from ai_db_fixtures import FakePgAdminClient, make_service
from router import ai_db_router
from service.audit_service import AuditAction, AuditCategory


@pytest.fixture
def fake_client():
    return FakePgAdminClient()


@pytest.fixture
def audit_records():
    with patch('util.audit_helper.audit_service.record') as mock_record:
        yield mock_record


def make_client(service_factory):
    ai_db_router.set_service_factory(service_factory)
    app = Flask(__name__)
    app.register_blueprint(ai_db_router.ai_db_bp)
    return app.test_client()


@pytest.fixture
def client(fake_client):
    yield make_client(lambda: make_service(fake_client))
    ai_db_router.set_service_factory(None)


@pytest.fixture
def unavailable_client():
    yield make_client(lambda: make_service(None))
    ai_db_router.set_service_factory(None)


def recorded_details(audit_records) -> list:
    return [call.args[3] for call in audit_records.call_args_list]


# ---- 조회 ----

def test_상태는_버전과_외부_주소를_준다(client):
    body = client.get('/ai-db/status').get_json()
    assert body['is_connected'] is True
    assert body['server_version'] == '17.2'
    assert body['public_port'] == 5432


def test_목록은_DB와_계정을_준다(client):
    assert [d['name'] for d in client.get('/ai-db/databases').get_json()['databases']] == ['gbrain', 'gbrain_elum']
    assert 'elum_member' in [r['name'] for r in client.get('/ai-db/roles').get_json()['roles']]


# ---- 미설정 ----

@pytest.mark.parametrize('method,path,body', [
    ('get', '/ai-db/status', None),
    ('get', '/ai-db/databases', None),
    ('post', '/ai-db/databases', {'name': 'team_db'}),
    ('post', '/ai-db/roles', {'name': 'team_a'}),
    ('delete', '/ai-db/roles/team_a', {'confirm_name': 'team_a'}),
    ('put', '/ai-db/databases/team_db/grants/team_a', None),
])
def test_관리_접속_정보가_없으면_503(unavailable_client, audit_records, method, path, body):
    response = getattr(unavailable_client, method)(path, json=body)
    assert response.status_code == 503
    assert response.get_json()['error'] == 'ai_db_unavailable'


# ---- 검증 오류 ----

def test_이름_규칙_위반은_400(client, fake_client, audit_records):
    response = client.post('/ai-db/databases', json={'name': 'x"; drop'})
    assert (response.status_code, response.get_json()['error']) == (400, 'invalid_name')
    assert fake_client.calls == []


def test_본문이_객체가_아니면_400(client, audit_records):
    response = client.post('/ai-db/roles', json=['team_a'])
    assert (response.status_code, response.get_json()['error']) == (400, 'bad_request')


@pytest.mark.parametrize('method,path,target', [
    ('delete', '/ai-db/databases/gbrain', 'gbrain'),
    ('delete', '/ai-db/databases/postgres', 'postgres'),
    ('post', '/ai-db/roles/ai_db_admin/password', 'ai_db_admin'),
    ('delete', '/ai-db/roles/postgres', 'postgres'),
    ('put', '/ai-db/databases/gbrain_elum/grants/pg_x', 'pg_x'),
    ('delete', '/ai-db/databases/gbrain_elum/grants/gbrain', 'gbrain'),
])
def test_보호_대상은_403이고_감사에_실패로_남는다(client, fake_client, audit_records, method, path, target):
    response = getattr(client, method)(path, json={'confirm_name': target})

    assert (response.status_code, response.get_json()['error']) == (403, 'protected_object')
    assert fake_client.calls == []
    assert audit_records.call_args.kwargs['success'] is False


def test_삭제_확인_불일치는_400(client, fake_client, audit_records):
    response = client.delete('/ai-db/databases/gbrain_elum', json={'confirm_name': 'other'})
    assert (response.status_code, response.get_json()['error']) == (400, 'confirm_mismatch')
    assert 'gbrain_elum' in fake_client.databases


def test_확인_이름이_같으면_삭제한다(client, fake_client, audit_records):
    response = client.delete('/ai-db/databases/gbrain_elum', json={'confirm_name': 'gbrain_elum'})
    assert response.status_code == 200
    assert 'gbrain_elum' not in fake_client.databases
    category, action = audit_records.call_args.args[:2]
    assert (category, action) == (AuditCategory.AI_DB, AuditAction.AI_DB_DATABASE_DELETE)


def test_중복은_409(client, audit_records):
    response = client.post('/ai-db/roles', json={'name': 'elum_member'})
    assert (response.status_code, response.get_json()['error']) == (409, 'already_exists')


def test_없는_대상은_404(client, audit_records):
    response = client.delete('/ai-db/roles/nobody_here', json={'confirm_name': 'nobody_here'})
    assert (response.status_code, response.get_json()['error']) == (404, 'not_found')


def test_접속_중인_DB_삭제는_409(client, fake_client, audit_records):
    fake_client.busy_databases.add('gbrain_elum')
    response = client.delete('/ai-db/databases/gbrain_elum', json={'confirm_name': 'gbrain_elum'})
    assert (response.status_code, response.get_json()['error']) == (409, 'database_in_use')


# ---- 비번 1회 노출 ----

def test_계정_만들기_응답에만_비번이_있고_감사_로그_목록에는_없다(client, audit_records, caplog):
    caplog.set_level(logging.DEBUG)

    response = client.post('/ai-db/roles', json={'name': 'team_a', 'database': 'gbrain_elum'})
    body = response.get_json()

    assert response.status_code == 201
    assert body['password']
    assert body['connection_url'].startswith('postgresql://team_a:')
    assert recorded_details(audit_records) == [{'role': 'team_a', 'database': 'gbrain_elum'}]
    assert body['password'] not in caplog.text
    assert body['password'] not in client.get('/ai-db/roles').get_data(as_text=True)


def test_비번_재발급도_1회_응답_감사에는_이름만(client, audit_records, caplog):
    caplog.set_level(logging.DEBUG)

    body = client.post('/ai-db/roles/elum_member/password', json={'database': 'gbrain_elum'}).get_json()

    assert body['connection_url'].endswith('@ai.postgres.example.com:5432/gbrain_elum')
    assert audit_records.call_args.args[1] == AuditAction.AI_DB_ROLE_PASSWORD_RESET
    assert body['password'] not in json.dumps(recorded_details(audit_records))
    assert body['password'] not in caplog.text


# ---- 권한 주기·빼기 ----

def test_권한_주기와_빼기는_클라이언트로_위임된다(client, fake_client, audit_records):
    assert client.put('/ai-db/databases/gbrain_elum/grants/elum_member').status_code == 200
    assert client.delete('/ai-db/databases/gbrain_elum/grants/elum_member').status_code == 200

    assert fake_client.calls == [('grant', 'gbrain_elum', 'elum_member'), ('revoke', 'gbrain_elum', 'elum_member')]
    assert [call.args[1] for call in audit_records.call_args_list] == [AuditAction.AI_DB_GRANT, AuditAction.AI_DB_REVOKE]


def test_DB_만들기는_계정_권한까지_넘긴다(client, fake_client, audit_records):
    response = client.post('/ai-db/databases', json={'name': 'team_db', 'owner_role': 'elum_member'})
    assert response.status_code == 201
    assert fake_client.calls == [('create_database', 'team_db', 'elum_member')]
    assert audit_records.call_args.args[3] == {'database': 'team_db', 'owner_role': 'elum_member'}


# ---- gbrain 팀 브레인 ----

def test_gbrain_상태는_준비_전이면_오류_없이_미준비(client):
    response = client.get('/ai-db/databases/gbrain_elum/gbrain')
    assert response.status_code == 200
    assert response.get_json()['is_ready'] is False


def test_gbrain_준비와_읽기_권한_주기_빼기는_감사_대상이다(client, fake_client, audit_records):
    body = {'writer_role': 'elum_member'}
    assert client.post('/ai-db/databases/gbrain_elum/gbrain/prepare', json=body).status_code == 200
    assert client.put('/ai-db/databases/gbrain_elum/gbrain/readers/team_a', json=body).status_code == 200
    assert client.delete('/ai-db/databases/gbrain_elum/gbrain/readers/team_a', json=body).status_code == 200

    assert [call[0] for call in fake_client.calls] == ['prepare_gbrain', 'grant_gbrain_reader', 'revoke_gbrain_reader']
    assert [call.args[1] for call in audit_records.call_args_list] == [
        AuditAction.AI_DB_GBRAIN_PREPARE, AuditAction.AI_DB_GBRAIN_READER_GRANT, AuditAction.AI_DB_GBRAIN_READER_REVOKE]
    assert recorded_details(audit_records)[1] == {'database': 'gbrain_elum', 'role': 'team_a', 'writer_role': 'elum_member'}


@pytest.mark.parametrize('method,path,body,status_code,error', [
    ('put', '/ai-db/databases/gbrain_elum/gbrain/readers/ai_db_admin', {'writer_role': 'elum_member'}, 403, 'protected_object'),
    ('post', '/ai-db/databases/gbrain/gbrain/prepare', {'writer_role': 'elum_member'}, 403, 'protected_object'),
    ('put', '/ai-db/databases/gbrain_elum/gbrain/readers/team_a', {'writer_role': 'Bad-Name'}, 400, 'invalid_name'),
    ('put', '/ai-db/databases/gbrain_elum/gbrain/readers/team_a', {}, 400, 'invalid_name'),
    ('put', '/ai-db/databases/gbrain_elum/gbrain/readers/team_a', {'writer_role': 'team_a'}, 400, 'same_reader_writer'),
])
def test_gbrain_검증_실패는_클라이언트를_부르지_않는다(client, fake_client, audit_records, method, path, body, status_code, error):
    response = getattr(client, method)(path, json=body)
    assert (response.status_code, response.get_json()['error']) == (status_code, error)
    assert fake_client.calls == []


def test_gbrain_ops_미설치는_409와_설치_안내(client, fake_client, audit_records):
    fake_client.ops_missing_databases.add('gbrain_elum')
    response = client.post('/ai-db/databases/gbrain_elum/gbrain/prepare', json={'writer_role': 'elum_member'})
    body = response.get_json()
    assert (response.status_code, body['error']) == (409, 'gbrain_ops_missing')
    assert 'sql/ai_db_ops_gbrain.sql' in body['message']
