"""gbrain 팀원·팀원 키 서비스 (#221): 발급 암호화 보관, 다시 보기 재확인·잠금, 종료 일괄 폐기, 기존 토큰 연결 (gbrain·DB 는 가짜)"""
import pytest

from service import secret_cipher
from service.gbrain_member_key_service import GbrainMemberKeyService, RevealAttemptGuard
from service.gbrain_member_service import GbrainMemberService
from service.gbrain_server_service import GbrainServerError
from gbrain_member_fakes import TEAM_BRAIN_ID, FakeBrainResolver, FakeMemberStore

ADMIN_KEY = 'admin-key-for-test'


@pytest.fixture(autouse=True)
def fast_cipher(monkeypatch):
    # 시험 속도: PBKDF2 반복 횟수만 줄임 (방식·형식은 같음)
    monkeypatch.setattr(secret_cipher, 'PBKDF2_ITERATIONS', 1000)
    monkeypatch.setenv('GBRAIN_MEMBER_KEY_SECRET', 'member-key-secret-for-test')


@pytest.fixture
def resolver():
    return FakeBrainResolver()


@pytest.fixture
def store():
    return FakeMemberStore()


@pytest.fixture
def member_service(resolver, store):
    return GbrainMemberService(brain_resolver=resolver, store=store)


@pytest.fixture
def key_service(resolver, store):
    return GbrainMemberKeyService(brain_resolver=resolver, store=store)


def add_member(member_service, handle='kim-dev'):
    return member_service.create_member(handle, '김개발', 'kim@example.com', '백엔드')


def test_발급하면_원문을_암호화해_보관하고_읽기_전용이_기본(member_service, key_service, store, resolver):
    member = add_member(member_service)

    issued = key_service.issue_key(member['id'], TEAM_BRAIN_ID)

    assert issued['token']['scopes'] == ['read'] and issued['token']['name'] == 'kim-dev-passql'
    stored = store.secret_by_key_id[issued['key']['id']]
    assert issued['secret'].encode() not in stored.encrypted_token
    assert 'secret' not in issued['key'] and issued['key']['has_stored_secret'] is True


def test_비밀_문구가_없으면_gbrain_발급_전에_막는다(member_service, key_service, resolver, monkeypatch):
    member = add_member(member_service)
    monkeypatch.delenv('GBRAIN_MEMBER_KEY_SECRET')

    with pytest.raises(GbrainServerError) as error:
        key_service.issue_key(member['id'])

    assert error.value.code == 'member_key_secret_missing' and error.value.status_code == 503
    assert resolver.token_service_by_brain['personal'].tokens == {}


def test_DB_저장이_실패하면_방금_만든_gbrain_토큰을_폐기한다(member_service, key_service, store, resolver):
    member = add_member(member_service)
    store.fail_insert_key = True

    with pytest.raises(GbrainServerError) as error:
        key_service.issue_key(member['id'])

    assert error.value.code == 'member_key_store_failed'
    tokens = list(resolver.token_service_by_brain['personal'].tokens.values())
    assert len(tokens) == 1 and tokens[0]['status'] == 'revoked'


def test_종료한_팀원에게는_발급하지_않는다(member_service, key_service, store):
    member = add_member(member_service)
    member_service.end_member(member['id'])

    with pytest.raises(GbrainServerError) as error:
        key_service.issue_key(member['id'])
    assert error.value.code == 'member_ended'


def test_다시_보기는_관리자_키가_맞을_때만_원문을_돌려준다(member_service, key_service):
    member = add_member(member_service)
    issued = key_service.issue_key(member['id'])

    with pytest.raises(GbrainServerError) as error:
        key_service.reveal_key(issued['key']['id'], 'wrong', ADMIN_KEY)
    assert error.value.code == 'admin_key_mismatch' and error.value.status_code == 403

    revealed = key_service.reveal_key(issued['key']['id'], ADMIN_KEY, ADMIN_KEY)
    assert revealed['secret'] == issued['secret']


def test_요청에_관리자_키가_없으면_다시_보기를_거부한다(member_service, key_service):
    issued = key_service.issue_key(add_member(member_service)['id'])

    with pytest.raises(GbrainServerError) as error:
        key_service.reveal_key(issued['key']['id'], '', None)
    assert error.value.code == 'admin_key_mismatch'


def test_재확인을_여러_번_틀리면_잠그고_창이_지나면_풀린다():
    now = [0.0]
    guard = RevealAttemptGuard(failure_limit=2, window_seconds=600, clock=lambda: now[0])
    for _ in range(2):
        with pytest.raises(GbrainServerError):
            guard.check_admin_key('wrong', ADMIN_KEY)

    with pytest.raises(GbrainServerError) as error:
        guard.check_admin_key(ADMIN_KEY, ADMIN_KEY)
    assert error.value.code == 'reveal_locked' and error.value.status_code == 429

    now[0] = 601.0
    guard.check_admin_key(ADMIN_KEY, ADMIN_KEY)


def test_폐기한_키와_원문_없는_연결_키는_다시_볼_수_없다(member_service, key_service, resolver):
    member = add_member(member_service)
    issued = key_service.issue_key(member['id'])
    key_service.revoke_key(issued['key']['id'])
    with pytest.raises(GbrainServerError) as error:
        key_service.reveal_key(issued['key']['id'], ADMIN_KEY, ADMIN_KEY)
    assert error.value.code == 'already_revoked'

    token_id = resolver.token_service_by_brain['personal'].add_existing_token('claude-code-mac-public')
    linked = key_service.link_token(1, 'personal', token_id)
    with pytest.raises(GbrainServerError) as error:
        key_service.reveal_key(linked['id'], ADMIN_KEY, ADMIN_KEY)
    assert error.value.code == 'secret_not_stored'


def test_비밀_문구가_바뀌면_복호화_실패를_알린다(member_service, key_service, monkeypatch):
    issued = key_service.issue_key(add_member(member_service)['id'])
    monkeypatch.setenv('GBRAIN_MEMBER_KEY_SECRET', 'another-secret')

    with pytest.raises(GbrainServerError) as error:
        key_service.reveal_key(issued['key']['id'], ADMIN_KEY, ADMIN_KEY)
    assert error.value.code == 'decrypt_failed'


def test_기존_기기_토큰을_소유자에게_연결한다(key_service, resolver, store):
    personal_tokens = resolver.token_service_by_brain['personal']
    token_id = personal_tokens.add_existing_token('claude-code-mac-public')
    personal_tokens.add_existing_token('old-laptop', status='revoked')

    candidates = key_service.list_unrecorded_tokens('personal')
    assert [token['name'] for token in candidates] == ['claude-code-mac-public']

    linked = key_service.link_token(1, 'personal', token_id)
    assert linked['member_id'] == 1 and linked['has_stored_secret'] is False
    assert key_service.list_unrecorded_tokens('personal') == []
    with pytest.raises(GbrainServerError) as error:
        key_service.link_token(1, 'personal', token_id)
    assert error.value.code in ('already_linked', 'token_not_found')


def test_팀원_종료는_모든_키를_gbrain_에서_폐기하고_종료한다(member_service, key_service, resolver, store):
    member = add_member(member_service)
    personal_key = key_service.issue_key(member['id'])
    team_key = key_service.issue_key(member['id'], TEAM_BRAIN_ID)

    result = member_service.end_member(member['id'])

    assert result['is_ended'] is True
    assert sorted(result['revoked_key_ids']) == sorted([personal_key['key']['id'], team_key['key']['id']])
    assert all(not token['is_active'] for service in resolver.token_service_by_brain.values()
               for token in service.tokens.values())
    assert store.members[member['id']].is_active is False


def test_종료_중_일부_폐기가_실패하면_팀원은_활성으로_두고_다시_누르면_남은_것만(member_service, key_service, resolver, store):
    member = add_member(member_service)
    key_service.issue_key(member['id'])
    team_key = key_service.issue_key(member['id'], TEAM_BRAIN_ID)
    team_tokens = resolver.token_service_by_brain[TEAM_BRAIN_ID]
    team_tokens.revoke_error_by_id[team_key['token']['id']] = GbrainServerError('x', 'unreachable')

    first = member_service.end_member(member['id'])
    assert first['is_ended'] is False and [failure['key_id'] for failure in first['failures']] == [team_key['key']['id']]
    assert store.members[member['id']].is_active is True

    team_tokens.revoke_error_by_id.clear()
    second = member_service.end_member(member['id'])
    assert second['is_ended'] is True and second['revoked_key_ids'] == [team_key['key']['id']]


def test_이미_gbrain_에서_폐기된_키도_종료를_막지_않는다(member_service, key_service, resolver):
    member = add_member(member_service)
    issued = key_service.issue_key(member['id'])
    resolver.token_service_by_brain['personal'].revoke_token(issued['token']['id'])

    assert member_service.end_member(member['id'])['is_ended'] is True


def test_소유자는_종료할_수_없다(member_service):
    with pytest.raises(GbrainServerError) as error:
        member_service.end_member(1)
    assert error.value.code == 'owner_cannot_end'


def test_사람별_보기는_gbrain_상태와_마지막_사용을_붙이고_폐기를_반영한다(member_service, key_service, resolver, store):
    member = add_member(member_service)
    issued = key_service.issue_key(member['id'])
    team_key = key_service.issue_key(member['id'], TEAM_BRAIN_ID)
    resolver.token_service_by_brain['personal'].revoke_token(issued['token']['id'])
    resolver.token_service_by_brain[TEAM_BRAIN_ID].list_error = GbrainServerError('x', 'unreachable')

    keys = {key['id']: key for key in member_service.describe_member_keys(member['id'])}

    assert keys[issued['key']['id']]['is_revoked'] is True
    assert keys[team_key['key']['id']]['live_status'] == 'unknown'
    assert all('secret' not in key and 'encrypted_token' not in key for key in keys.values())


def test_팀원_입력_검증(member_service):
    with pytest.raises(GbrainServerError) as error:
        member_service.create_member('Kim', '김')
    assert error.value.code == 'invalid_handle'
    with pytest.raises(GbrainServerError) as error:
        member_service.create_member('kim-dev', '   ')
    assert error.value.code == 'invalid_display_name'
    add_member(member_service)
    with pytest.raises(GbrainServerError) as error:
        add_member(member_service)
    assert error.value.code == 'handle_in_use'


def test_DB_가_없으면_503(member_service, store):
    store.is_unavailable = True
    with pytest.raises(GbrainServerError) as error:
        member_service.list_members()
    assert error.value.code == 'member_store_unavailable' and error.value.status_code == 503
