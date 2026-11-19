"""
AI 서버 공용 PG 관리 API (/ai-db/*, nginx X-API-Key 보호): DB·계정 목록·생성·삭제, 비번 재발급, 접속 권한, gbrain 팀 브레인
변경 API 전부 @audited, 감사 상세는 이름만 (비번·연결 문자열 제외)
"""
from flask import Blueprint, jsonify, request

from config.ai_db_config import get_admin_url, get_public_host, get_public_port
from service.ai_db.ai_db_errors import AiDbError, AiDbUnavailable, BadRequest
from service.ai_db.ai_db_service import AiDbService
from service.ai_db.pg_admin_client import PgAdminClient
from service.audit_service import AuditAction, AuditCategory
from util.audit_helper import audited, set_audit_detail

ai_db_bp = Blueprint('ai_db', __name__, url_prefix='/ai-db')

# 오류 코드 > HTTP 상태 (없는 코드는 502: PG 쪽 예상 밖 실패)
ERROR_STATUS_CODES = {
    'ai_db_unavailable': 503,
    'bad_request': 400, 'invalid_name': 400, 'confirm_mismatch': 400, 'same_reader_writer': 400,
    'protected_object': 403, 'permission_denied': 403,
    'not_found': 404,
    'already_exists': 409, 'database_in_use': 409, 'role_in_use': 409,
    'gbrain_ops_missing': 409,
}
# gbrain_ops_missing 운영자 안내 (대상 DB 에 슈퍼유저로 1회 실행)
GBRAIN_OPS_MISSING_MESSAGE = "Run suh-ai-server/sql/ai_db_ops_gbrain.sql as superuser in this database"
UNEXPECTED_ERROR_STATUS_CODE = 502


def build_default_service() -> AiDbService:
    """요청마다 설정 다시 읽기 (비밀 파일 교체 시 재시작 불필요)"""
    admin_url = get_admin_url()
    client = PgAdminClient(admin_url) if admin_url else None
    return AiDbService(client, get_public_host(), get_public_port())


# 테스트에서 가짜 클라이언트를 심는 지점
_service_factory = build_default_service


def set_service_factory(factory) -> None:
    global _service_factory
    _service_factory = factory or build_default_service


def _service() -> AiDbService:
    return _service_factory()


def _error(code: str, status_code: int = None, **extra):
    return jsonify({'error': code, **extra}), status_code or ERROR_STATUS_CODES.get(code, UNEXPECTED_ERROR_STATUS_CODE)


@ai_db_bp.errorhandler(AiDbError)
def _handle_ai_db_error(error: AiDbError):
    if error.code == 'gbrain_ops_missing':
        return _error(error.code, message=GBRAIN_OPS_MISSING_MESSAGE)
    return _error(error.code)


def _json_body() -> dict:
    """본문 JSON 객체 (없으면 빈 dict, 객체 아니면 bad_request)"""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise BadRequest()
    return body


def _optional_text(body: dict, key: str):
    value = body.get(key)
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise BadRequest()
    return value


# ---- 조회 ----

@ai_db_bp.route('/status', methods=['GET'])
def status():
    """연결 상태·서버 버전·외부 주소 (미연결도 외부 주소는 함께)"""
    service = _service()
    try:
        return jsonify(service.get_status())
    except AiDbUnavailable:
        return _error('ai_db_unavailable', is_connected=False,
                      public_host=service.public_host, public_port=service.public_port)


@ai_db_bp.route('/databases', methods=['GET'])
def list_databases():
    return jsonify({'databases': _service().list_databases()})


@ai_db_bp.route('/roles', methods=['GET'])
def list_roles():
    return jsonify({'roles': _service().list_roles()})


# ---- DB ----

@ai_db_bp.route('/databases', methods=['POST'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_DATABASE_CREATE)
def create_database():
    body = _json_body()
    name, owner_role = body.get('name'), _optional_text(body, 'owner_role')
    set_audit_detail({'database': name if isinstance(name, str) else None, 'owner_role': owner_role})
    return jsonify(_service().create_database(name, owner_role)), 201


@ai_db_bp.route('/databases/<name>', methods=['DELETE'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_DATABASE_DELETE)
def delete_database(name):
    set_audit_detail({'database': name})
    _service().delete_database(name, _json_body().get('confirm_name'))
    return jsonify({'ok': True})


# ---- 계정 ----

@ai_db_bp.route('/roles', methods=['POST'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_ROLE_CREATE)
def create_role():
    """응답에만 비번·연결 문자열 1회 (저장·감사·로그 없음)"""
    body = _json_body()
    name, database_name = body.get('name'), _optional_text(body, 'database')
    set_audit_detail({'role': name if isinstance(name, str) else None, 'database': database_name})
    return jsonify(_service().create_role(name, database_name)), 201


@ai_db_bp.route('/roles/<name>/password', methods=['POST'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_ROLE_PASSWORD_RESET)
def reset_role_password(name):
    database_name = _optional_text(_json_body(), 'database')
    set_audit_detail({'role': name, 'database': database_name})
    return jsonify(_service().reset_password(name, database_name))


@ai_db_bp.route('/roles/<name>', methods=['DELETE'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_ROLE_DELETE)
def delete_role(name):
    set_audit_detail({'role': name})
    _service().delete_role(name, _json_body().get('confirm_name'))
    return jsonify({'ok': True})


# ---- 접속 권한 ----

@ai_db_bp.route('/databases/<database_name>/grants/<role_name>', methods=['PUT'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_GRANT)
def grant_access(database_name, role_name):
    set_audit_detail({'database': database_name, 'role': role_name})
    _service().grant(database_name, role_name)
    return jsonify({'ok': True})


@ai_db_bp.route('/databases/<database_name>/grants/<role_name>', methods=['DELETE'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_REVOKE)
def revoke_access(database_name, role_name):
    set_audit_detail({'database': database_name, 'role': role_name})
    _service().revoke(database_name, role_name)
    return jsonify({'ok': True})


# ---- gbrain 팀 브레인 (본문 writer_role 필수: 읽기 기본 권한의 기준 계정) ----

@ai_db_bp.route('/databases/<database_name>/gbrain', methods=['GET'])
def gbrain_status(database_name):
    """준비 여부·쓰기 계정·읽기 팀원 (ops 스키마·pages 표 없어도 오류 아님)"""
    return jsonify(_service().get_gbrain_status(database_name))


@ai_db_bp.route('/databases/<database_name>/gbrain/prepare', methods=['POST'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_GBRAIN_PREPARE)
def prepare_gbrain(database_name):
    writer_role = _optional_text(_json_body(), 'writer_role')
    set_audit_detail({'database': database_name, 'writer_role': writer_role})
    _service().prepare_gbrain(database_name, writer_role)
    return jsonify({'ok': True})


@ai_db_bp.route('/databases/<database_name>/gbrain/readers/<role_name>', methods=['PUT'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_GBRAIN_READER_GRANT)
def grant_gbrain_reader(database_name, role_name):
    writer_role = _optional_text(_json_body(), 'writer_role')
    set_audit_detail({'database': database_name, 'role': role_name, 'writer_role': writer_role})
    _service().grant_gbrain_reader(database_name, role_name, writer_role)
    return jsonify({'ok': True})


@ai_db_bp.route('/databases/<database_name>/gbrain/readers/<role_name>', methods=['DELETE'])
@audited(AuditCategory.AI_DB, AuditAction.AI_DB_GBRAIN_READER_REVOKE)
def revoke_gbrain_reader(database_name, role_name):
    writer_role = _optional_text(_json_body(), 'writer_role')
    set_audit_detail({'database': database_name, 'role': role_name, 'writer_role': writer_role})
    _service().revoke_gbrain_reader(database_name, role_name, writer_role)
    return jsonify({'ok': True})
