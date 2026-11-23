"""gbrain_member_router (#221): 원문은 발급·다시 보기 응답에만, 목록·로그·감사 상세에는 절대 없음, 상태 변경은 모두 감사"""
import json
import logging

import pytest

from app import app as flask_app
from router import gbrain_member_router as router_module
from service import secret_cipher
from service.audit_service import AuditAction
from service.gbrain_member_key_service import GbrainMemberKeyService
from service.gbrain_member_service import GbrainMemberService
from gbrain_member_fakes import TEAM_BRAIN_ID, FakeBrainResolver, FakeMemberStore

ADMIN_KEY = 'admin-key-for-test'


@pytest.fixture
def resolver(monkeypatch):
    monkeypatch.setattr(secret_cipher, 'PBKDF2_ITERATIONS', 1000)
    monkeypatch.setenv('GBRAIN_MEMBER_KEY_SECRET', 'member-key-secret-for-test')
    fake_resolver = FakeBrainResolver()
    store = FakeMemberStore()
    monkeypatch.setattr(router_module, 'member_service', GbrainMemberService(fake_resolver, store))
    monkeypatch.setattr(router_module, 'member_key_service', GbrainMemberKeyService(fake_resolver, store))
    return fake_resolver


@pytest.fixture
def audit_calls(monkeypatch):
    from util import audit_helper
    calls = []

    def fake_record(category, action, actor_ip, detail=None, **kwargs):
        calls.append({'action': action, 'detail': detail, 'success': kwargs.get('success')})
        return True
    monkeypatch.setattr(audit_helper.audit_service, 'record', fake_record)
    return calls


@pytest.fixture
def client():
    flask_app.config['TESTING'] = True
    with flask_app.test_client() as test_client:
        yield test_client


def create_member(client, handle='kim-dev'):
    return client.post('/gbrain/members', json={'handle': handle, 'display_name': '김개발'}).get_json()['member']


def issue_key(client, member_id, brain=None):
    response = client.post(f'/gbrain/members/{member_id}/keys', json={'brain': brain} if brain else {})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_원문은_목록_로그_감사_어디에도_남지_않는다(client, resolver, audit_calls, caplog):
    caplog.set_level(logging.DEBUG)
    member = create_member(client)
    issued = issue_key(client, member['id'], TEAM_BRAIN_ID)
    secret = issued['secret']
    reveal = client.post(f'/gbrain/member-keys/{issued["key"]["id"]}/reveal', json={'admin_key': ADMIN_KEY},
                         headers={'X-API-Key': ADMIN_KEY})
    assert reveal.get_json()['secret'] == secret

    list_bodies = [client.get('/gbrain/members').get_data(as_text=True),
                   client.get(f'/gbrain/members/{member["id"]}/keys').get_data(as_text=True),
                   client.get('/gbrain/members/unrecorded-tokens?brain=' + TEAM_BRAIN_ID).get_data(as_text=True)]
    for body in list_bodies:
        assert secret not in body and 'encrypted_token' not in body
    assert secret not in caplog.text and ADMIN_KEY not in caplog.text
    audit_text = json.dumps([call['detail'] for call in audit_calls], ensure_ascii=False, default=str)
    assert secret not in audit_text and ADMIN_KEY not in audit_text


def test_발급_응답은_결과_창_모양이고_no_store(client, resolver, audit_calls):
    member = create_member(client)
    issued = issue_key(client, member['id'], TEAM_BRAIN_ID)

    assert issued['token']['scopes'] == ['read'] and issued['is_team'] is True
    assert issued['mcp_server_name'] == 'gbrain-passql' and issued['secret'].startswith('gbrain_')
    response = client.get('/gbrain/members')
    assert response.headers['Cache-Control'] == 'no-store'
    assert audit_calls[-1]['action'] == AuditAction.GBRAIN_MEMBER_KEY_CREATE and audit_calls[-1]['success'] is True


def test_다시_보기는_성공과_실패를_모두_감사한다(client, resolver, audit_calls):
    member = create_member(client)
    key_id = issue_key(client, member['id'])['key']['id']

    wrong = client.post(f'/gbrain/member-keys/{key_id}/reveal', json={'admin_key': 'wrong'}, headers={'X-API-Key': ADMIN_KEY})
    right = client.post(f'/gbrain/member-keys/{key_id}/reveal', json={'admin_key': ADMIN_KEY}, headers={'X-API-Key': ADMIN_KEY})

    assert wrong.status_code == 403 and 'secret' not in wrong.get_json()
    assert right.status_code == 200 and right.get_json()['auto_hide_seconds'] > 0
    reveal_calls = [call for call in audit_calls if call['action'] == AuditAction.GBRAIN_MEMBER_KEY_REVEAL]
    assert [call['success'] for call in reveal_calls] == [False, True]
    assert reveal_calls[0]['detail']['code'] == 'admin_key_mismatch'


def test_비밀_문구가_없으면_목록에_알리고_발급은_503(client, resolver, monkeypatch):
    monkeypatch.delenv('GBRAIN_MEMBER_KEY_SECRET')
    member = create_member(client)

    listing = client.get('/gbrain/members').get_json()
    response = client.post(f'/gbrain/members/{member["id"]}/keys', json={})

    assert listing['is_key_secret_configured'] is False and listing['key_secret_env_name'] == 'GBRAIN_MEMBER_KEY_SECRET'
    assert response.status_code == 503 and response.get_json()['code'] == 'member_key_secret_missing'


def test_종료_일부_실패는_502_와_실패_목록(client, resolver, audit_calls):
    from service.gbrain_server_service import GbrainServerError
    member = create_member(client)
    issued = issue_key(client, member['id'])
    resolver.token_service_by_brain['personal'].revoke_error_by_id[issued['token']['id']] = GbrainServerError('x', 'unreachable')

    response = client.post(f'/gbrain/members/{member["id"]}/end')

    assert response.status_code == 502 and response.get_json()['code'] == 'member_end_partial'
    assert audit_calls[-1]['action'] == AuditAction.GBRAIN_MEMBER_END and audit_calls[-1]['success'] is False


def test_상태_변경_경로는_모두_감사한다(client, resolver, audit_calls):
    member = create_member(client)
    client.put(f'/gbrain/members/{member["id"]}', json={'memo': '프론트'})
    key_id = issue_key(client, member['id'])['key']['id']
    client.post(f'/gbrain/member-keys/{key_id}/revoke')
    token_id = resolver.token_service_by_brain['personal'].add_existing_token('claude-code-mac-public')
    client.post('/gbrain/members/1/keys/link', json={'brain': 'personal', 'token_id': token_id})
    client.post(f'/gbrain/members/{member["id"]}/end')

    assert [call['action'] for call in audit_calls] == [
        AuditAction.GBRAIN_MEMBER_CREATE, AuditAction.GBRAIN_MEMBER_UPDATE, AuditAction.GBRAIN_MEMBER_KEY_CREATE,
        AuditAction.GBRAIN_MEMBER_KEY_REVOKE, AuditAction.GBRAIN_MEMBER_KEY_LINK, AuditAction.GBRAIN_MEMBER_END]
    assert all(call['success'] for call in audit_calls)


def test_관리_화면에_팀원_카드가_있다(client):
    page = client.get('/admin/gbrain').get_data(as_text=True)

    assert 'id="member-table-body"' in page and 'gbrain-members.js' in page
