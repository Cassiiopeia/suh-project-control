"""
팀 브레인 만들기 실패 응답 (#226): code > 다음 할 일(next_step) 표, 실패 단계·끝난 단계 붙이기
모든 실패 응답 = code + 해요체 error + next_step + steps (+ failed_step, cause, writer_secret)
"""
from service.gbrain_server_service import GbrainServerError

DEFAULT_NEXT_STEP = '오류 코드와 서버 로그(관제소 > gbrain 서버 > 팀 브레인 로그)를 확인한 뒤 같은 요청을 다시 보내 주세요. 다시 보내도 끝난 단계는 그대로 둬요'

# code > 다음 할 일 (해요체, 화면·클라이언트 스킬이 그대로 보여 줌)
TEAM_NEXT_STEPS = {
    'invalid_project': '프로젝트 키를 영어 소문자로 시작하는 소문자·숫자 2~20자로 고쳐 다시 보내 주세요',
    'reserved_project': '다른 프로젝트 키로 다시 보내 주세요',
    'invalid_dry_run': 'dry_run 은 true 나 false 로 보내 주세요',
    'team_brain_not_found': '프로젝트 키를 확인하거나 GET /gbrain/teams 로 등록된 팀 브레인을 확인해 주세요',
    'team_registry_unreadable': 'AI 서버의 C:/AI/gbrain/teams/team-brains.json 이 올바른 JSON 인지 확인해 주세요 (덮어쓰지 말고 백업 뒤 고쳐 주세요)',
    'ai_db_unavailable': 'AI 서버 DB 관리 접속(C:/AI/secrets/ai-db-admin-url)과 gbrain-postgres 컨테이너가 살아 있는지 확인한 뒤 다시 보내 주세요',
    'team_database_not_empty_unknown': 'DB 에 팀 브레인이 아닌 객체가 있어요. 아무것도 지우지 않았어요. 응답의 found 값을 보고 그 DB 를 직접 정리하거나 다른 프로젝트 키를 써 주세요',
    'team_database_repair_unavailable': '이미 있는 DB 를 손보려면 슈퍼유저 접속(개인 gbrain 설정)이 필요해요. 개인 gbrain 설정을 확인하거나 슈퍼유저로 suh-ai-server/sql/ai_db_ops_gbrain.sql 을 그 DB 에 실행한 뒤 다시 보내 주세요',
    'team_database_repair_failed': '슈퍼유저로 DB 소유자를 ai_db_admin 으로 바꾸고 suh-ai-server/sql/ai_db_ops_gbrain.sql 을 그 DB 에 실행한 뒤 다시 보내 주세요',
    'team_writer_role_not_managed': '쓰기 계정을 ai_db_admin 이 관리하지 않아요. 슈퍼유저로 GRANT <쓰기 계정> TO ai_db_admin WITH ADMIN OPTION 을 실행한 뒤 다시 보내 주세요',
    'team_writer_role_cannot_login': '슈퍼유저로 ALTER ROLE <쓰기 계정> LOGIN 을 실행한 뒤 다시 보내 주세요',
    'team_writer_role_protected': '슈퍼유저 계정은 쓰기 계정으로 쓸 수 없어요. 다른 프로젝트 키를 써 주세요',
    'team_database_inspect_failed': 'cause 코드를 확인해 주세요. 살펴보기는 읽기만 해서 그대로 다시 보내도 돼요',
    'team_database_create_failed': 'cause 코드를 확인해 주세요. 만들다 남은 DB 는 지우지 않았고 다시 보내면 받아 써요',
    'team_writer_role_create_failed': 'cause 코드를 확인해 주세요. 다시 보내면 이어서 해요',
    'team_grant_failed': 'cause 코드를 확인해 주세요. 권한 적용은 다시 보내도 같은 결과라 그대로 다시 보내면 돼요',
    'team_prepare_failed': 'cause 가 gbrain_ops_missing 이면 슈퍼유저로 suh-ai-server/sql/ai_db_ops_gbrain.sql 을 그 DB 에 실행한 뒤 다시 보내 주세요',
    'writer_password_required': '동기화 맥 설정에 있는 기존 쓰기 계정 비밀번호를 writer_password 로 함께 보내 주세요 (비밀번호는 바꾸지 않아요)',
    'personal_config_unreadable': 'AI 서버의 개인 gbrain 설정 파일(~/.gbrain/config.json)을 확인해 주세요',
    'gbrain_init_failed': '쓰기 계정 권한과 비밀번호를 확인한 뒤 다시 보내 주세요. 권한은 다음 실행에서 다시 적용해요',
    'gbrain_migrate_failed': 'writer_password 가 맞는지 확인한 뒤 다시 보내 주세요',
    'service_install_failed': '팀 브레인 로그와 setup-gbrain-http.ps1 출력을 확인한 뒤 다시 보내 주세요',
    'nginx_not_found': 'AI 서버의 nginx 설치 폴더를 확인해 주세요',
    'nginx_test_failed': 'nginx 설정을 되돌려 뒀어요. nginx -t 출력을 확인한 뒤 다시 보내 주세요',
    'nginx_reload_failed': 'nginx 서비스 상태를 확인한 뒤 다시 보내 주세요',
    'team_create_unexpected': DEFAULT_NEXT_STEP,
}


def find_next_step(code: str) -> str:
    return TEAM_NEXT_STEPS.get(code, DEFAULT_NEXT_STEP)


def attach_failure_context(error: GbrainServerError, steps: dict, failed_step=None) -> GbrainServerError:
    """오류에 끝난 단계·실패 단계·다음 할 일 붙이기 (이미 붙은 값은 유지)"""
    error.details = {**(error.details or {}), 'steps': dict(steps)}
    if failed_step:
        error.details.setdefault('failed_step', failed_step)
    error.details.setdefault('next_step', find_next_step(error.code))
    return error
