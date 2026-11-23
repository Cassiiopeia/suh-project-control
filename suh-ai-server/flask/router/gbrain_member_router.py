"""
gbrain 팀원·팀원 키 관리 API (#221): 관리 페이지 /admin/gbrain 팀원 카드가 사용
nginx /api/flask/ X-API-Key 뒤에서만 동작, 상태 변경은 모두 감사 기록 (원문 없음)
모든 응답 Cache-Control: no-store (발급·다시 보기 응답에 원문이 실림)
브레인 결정·연결 안내 값은 토큰 카드 라우터(gbrain_token_router) 규칙을 그대로 씀
"""
from flask import Blueprint, jsonify, request

from config import gbrain_member_key_config as member_key_config
from router import gbrain_token_router
from service.audit_service import AuditAction, AuditCategory
from service.gbrain_member_key_service import GbrainMemberKeyService
from service.gbrain_member_service import GbrainMemberService
from service.gbrain_server_service import GbrainServerError
from util.audit_helper import audited, set_audit_detail

gbrain_member_bp = Blueprint('gbrain_member', __name__)

# 감사 상세 문자열 최대 길이
AUDIT_TEXT_MAX_LENGTH = 64


def _resolve_brain(brain_id):
    # 테스트에서 토큰 라우터의 가짜 서비스가 그대로 쓰이도록 호출 시점에 읽음
    return gbrain_token_router._resolve_brain(brain_id)


# 테스트에서 monkeypatch 로 교체하는 지점 (키 서비스는 다시 보기 실패 잠금 상태를 가짐 > 모듈 단일 객체)
member_service = GbrainMemberService(brain_resolver=_resolve_brain)
member_key_service = GbrainMemberKeyService(brain_resolver=_resolve_brain)


def _members():
    return member_service


def _keys():
    return member_key_service


def _error_response(error: GbrainServerError):
    return gbrain_token_router._error_response(error)


def _ok(body: dict):
    return gbrain_token_router._no_store(jsonify({'success': True, **body}), 200)


def _read_body() -> dict:
    return request.get_json(silent=True) or {}


def _to_result_window_body(created_or_revealed: dict) -> dict:
    """발급·다시 보기 > 토큰 카드 결과 창과 같은 모양 (token·secret·연결 안내 값)"""
    key = created_or_revealed['key']
    token = created_or_revealed.get('token') or {
        'id': key['gbrain_token_id'], 'name': key['token_name'], 'scopes': key['scopes']}
    return {'key': key, 'token': token, 'secret': created_or_revealed['secret'],
            'auto_hide_seconds': member_key_config.REVEAL_AUTO_HIDE_SECONDS,
            **gbrain_token_router._brain_fields(created_or_revealed['instance'])}


# ---------- 팀원 ----------
@gbrain_member_bp.route('/gbrain/members', methods=['GET'])
def list_members():
    """팀원 목록 + 키 요약 (원문 없음) + 암호화 비밀 문구 설정 여부"""
    try:
        members = _members().list_members()
    except GbrainServerError as error:
        return _error_response(error)
    return _ok({'members': members,
                'is_key_secret_configured': member_key_config.is_member_key_secret_configured(),
                'key_secret_env_name': member_key_config.ENV_MEMBER_KEY_SECRET})


@gbrain_member_bp.route('/gbrain/members', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_CREATE)
def create_member():
    body = _read_body()
    set_audit_detail({'handle': str(body.get('handle'))[:AUDIT_TEXT_MAX_LENGTH]})
    try:
        member = _members().create_member(body.get('handle'), body.get('display_name'),
                                          body.get('contact'), body.get('memo'))
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'member_id': member['id']})
    return _ok({'member': member})


@gbrain_member_bp.route('/gbrain/members/<int:member_id>', methods=['PUT'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_UPDATE)
def update_member(member_id):
    body = _read_body()
    set_audit_detail({'member_id': member_id, 'fields': sorted(name for name in body
                                                               if name in ('display_name', 'contact', 'memo'))})
    try:
        member = _members().update_member(member_id, body.get('display_name'), body.get('contact'), body.get('memo'))
    except GbrainServerError as error:
        return _error_response(error)
    return _ok({'member': member})


@gbrain_member_bp.route('/gbrain/members/<int:member_id>/end', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_END)
def end_member(member_id):
    """키 일괄 폐기 > 종료 (일부 실패면 207 + 실패 목록, 다시 누르면 남은 것만)"""
    set_audit_detail({'member_id': member_id})
    try:
        result = _members().end_member(member_id)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'revoked_key_ids': result['revoked_key_ids'],
                      'failed_key_ids': [failure['key_id'] for failure in result['failures']]})
    if result['failures']:
        body = {'success': False, 'error': '일부 키를 폐기하지 못해서 팀원을 종료하지 않았어요. 다시 눌러 주세요',
                'code': 'member_end_partial', **result}
        return gbrain_token_router._no_store(jsonify(body), 502)
    return _ok(result)


@gbrain_member_bp.route('/gbrain/members/<int:member_id>/keys', methods=['GET'])
def list_member_keys(member_id):
    """사람별 보기: 키 + gbrain 상태·마지막 사용 (원문 없음)"""
    try:
        keys = _members().describe_member_keys(member_id)
    except GbrainServerError as error:
        return _error_response(error)
    return _ok({'keys': keys})


# ---------- 키 ----------
@gbrain_member_bp.route('/gbrain/members/<int:member_id>/keys', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_KEY_CREATE)
def issue_member_key(member_id):
    """발급: 원문은 이 응답에만 (감사·로그 제외)"""
    body = _read_body()
    set_audit_detail({'member_id': member_id, 'brain': str(body.get('brain'))[:AUDIT_TEXT_MAX_LENGTH],
                      'scope_preset': str(body.get('scope_preset'))[:AUDIT_TEXT_MAX_LENGTH]})
    try:
        issued = _keys().issue_key(member_id, body.get('brain'), body.get('name'), body.get('scope_preset'))
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'key_id': issued['key']['id'], 'token_id': issued['token']['id'],
                      'scopes': issued['token']['scopes']})
    return _ok(_to_result_window_body(issued))


@gbrain_member_bp.route('/gbrain/member-keys/<int:key_id>/revoke', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_KEY_REVOKE)
def revoke_member_key(key_id):
    set_audit_detail({'key_id': key_id})
    try:
        key = _keys().revoke_key(key_id)
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'member_id': key['member_id'], 'brain': key['brain'], 'token_id': key['gbrain_token_id']})
    return _ok({'key': key})


@gbrain_member_bp.route('/gbrain/member-keys/<int:key_id>/reveal', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_KEY_REVEAL)
def reveal_member_key(key_id):
    """다시 보기: 관리자 키 재입력 <-> 요청 X-API-Key, 성공·실패 모두 감사 (입력값·원문은 기록 안 함)"""
    set_audit_detail({'key_id': key_id})
    try:
        revealed = _keys().reveal_key(key_id, _read_body().get('admin_key'), request.headers.get('X-API-Key'))
    except GbrainServerError as error:
        set_audit_detail({'code': error.code})
        return _error_response(error)
    set_audit_detail({'member_id': revealed['key']['member_id'], 'brain': revealed['key']['brain'],
                      'token_id': revealed['key']['gbrain_token_id']})
    return _ok(_to_result_window_body(revealed))


@gbrain_member_bp.route('/gbrain/members/unrecorded-tokens', methods=['GET'])
def list_unrecorded_tokens():
    """기존 토큰 연결 후보: 브레인의 살아 있는 gbrain 토큰 중 DB 에 없는 것"""
    try:
        tokens = _keys().list_unrecorded_tokens(request.args.get('brain'))
    except GbrainServerError as error:
        return _error_response(error)
    return _ok({'tokens': tokens})


@gbrain_member_bp.route('/gbrain/members/<int:member_id>/keys/link', methods=['POST'])
@audited(AuditCategory.GBRAIN, AuditAction.GBRAIN_MEMBER_KEY_LINK)
def link_member_key(member_id):
    body = _read_body()
    set_audit_detail({'member_id': member_id, 'brain': str(body.get('brain'))[:AUDIT_TEXT_MAX_LENGTH],
                      'token_id': str(body.get('token_id'))[:AUDIT_TEXT_MAX_LENGTH]})
    try:
        key = _keys().link_token(member_id, body.get('brain'), body.get('token_id'))
    except GbrainServerError as error:
        return _error_response(error)
    set_audit_detail({'key_id': key['id']})
    return _ok({'key': key})
