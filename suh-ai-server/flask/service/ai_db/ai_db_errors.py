"""AI 서버 DB 관리 오류: 오류 코드(snake_case)만 들고 다님, HTTP 상태는 라우터가 결정"""


class AiDbError(Exception):
    """AI 서버 DB 관리 공통 오류 (code = 응답 error 값)"""
    code = "ai_db_error"

    def __init__(self, code: str = None):
        super().__init__(code or self.code)
        if code:
            self.code = code


# ---- PG 접속·실행 결과 ----

class AiDbUnavailable(AiDbError):
    """관리 접속 정보 없음 / PG 접속 실패"""
    code = "ai_db_unavailable"


class NotFound(AiDbError):
    code = "not_found"


class AlreadyExists(AiDbError):
    code = "already_exists"


class DatabaseInUse(AiDbError):
    """접속 중인 DB 삭제 시도 (WITH FORCE 미사용)"""
    code = "database_in_use"


class RoleInUse(AiDbError):
    """권한·소유 객체가 남은 계정 삭제 시도"""
    code = "role_in_use"


class PermissionDenied(AiDbError):
    """관리 계정(ai_db_admin) 권한 밖의 대상"""
    code = "permission_denied"


class GbrainOpsMissing(AiDbError):
    """대상 DB 에 ai_db_ops 함수 없음 (슈퍼유저로 sql/ai_db_ops_gbrain.sql 실행 필요)"""
    code = "gbrain_ops_missing"


# ---- 요청 검증 ----

class BadRequest(AiDbError):
    code = "bad_request"


class InvalidName(AiDbError):
    code = "invalid_name"


class SameReaderWriter(AiDbError):
    """읽기 계정 = 쓰기 계정 (쓰기 계정 BYPASSRLS 회수 방지)"""
    code = "same_reader_writer"


class ProtectedObject(AiDbError):
    code = "protected_object"


class ConfirmMismatch(AiDbError):
    code = "confirm_mismatch"
