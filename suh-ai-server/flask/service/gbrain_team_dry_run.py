"""
팀 브레인 dry_run 계획 (#226): 만들기와 같은 검사 > 단계별 계획, 아무것도 바꾸지 않음
바꾸지 않는 대상: DB·계정·권한, 등록부(포트는 미리보기만), 관리자 토큰·설정 파일, NSSM 서비스, nginx map
계획 값 (클라이언트 /pro-gbrain 계약): exists / would_create / would_adopt / would_regrant / refuse
"""
from service.gbrain_instance import to_team_database_name, to_team_writer_role
from service.gbrain_server_service import GbrainServerError
from service.gbrain_team_database_steps import PLAN_EXISTS, PLAN_REFUSE, PLAN_WOULD_CREATE, GbrainTeamDatabaseSteps
from service.gbrain_team_errors import find_next_step

# 서비스 상태: 설치 안 됨 (util/windows_service_client.STATE_NOT_INSTALLED 와 같음)
SERVICE_STATE_NOT_INSTALLED = 'not_installed'


def build_team_brain_plan(team_service, project: str, writer_password=None) -> dict:
    """{dry_run, can_create, brain(예정 값), plan, blockers[{code, error, next_step}], details}"""
    database_name, writer_role = to_team_database_name(project), to_team_writer_role(project)
    state = team_service.build_database_steps().inspect(database_name, writer_role)
    entry = team_service.run_registry(
        lambda: team_service.registry.preview_entry(project, database_name, writer_role))
    instance = team_service.registry.to_instance(entry)
    provisioner = team_service.provisioner
    blockers = list(state.blockers)

    # 단계별 계획 (DB 단계 > 파일·서비스·nginx 는 있는지만 확인)
    plan = GbrainTeamDatabaseSteps.plan(state)
    plan['admin_token'] = PLAN_EXISTS if provisioner.has_admin_token(instance) else PLAN_WOULD_CREATE
    plan['config'] = _plan_config(provisioner, instance, state, writer_password, blockers)
    service_state = team_service.read_service_state(instance)
    plan['service'] = PLAN_WOULD_CREATE if service_state == SERVICE_STATE_NOT_INSTALLED else PLAN_EXISTS
    plan['nginx'] = PLAN_EXISTS if provisioner.is_nginx_route_published(instance) else PLAN_WOULD_CREATE

    return {
        'dry_run': True,
        'can_create': not blockers,
        'brain': {
            'project': project, 'mcp_url': instance.mcp_url, 'mcp_server_name': instance.mcp_server_name,
            'database_name': database_name, 'writer_role': writer_role, 'service_name': instance.service_name,
            'port': instance.port, 'is_registered': entry['is_registered'], 'gbrain_home': instance.gbrain_home,
            'nginx_map_path': provisioner.get_nginx_map_path(instance),
        },
        'plan': plan,
        'blockers': [_describe_blocker(blocker) for blocker in blockers],
        'details': {'database_kind': state.kind, 'database_owner': state.database.get('owner'),
                    'database_repairs': state.repairs, 'writer_role_exists': bool(state.writer.get('exists')),
                    'service_state': service_state},
    }


def _plan_config(provisioner, instance, state, writer_password, blockers) -> str:
    """설정 있음 > exists, 새 계정이거나 비번 받음 > would_create, 기존 계정인데 비번 없음 > refuse"""
    if provisioner.has_brain_config(instance):
        return PLAN_EXISTS
    if not state.writer.get('exists') or writer_password:
        return PLAN_WOULD_CREATE
    blockers.append(GbrainServerError(f'{instance.writer_role} 계정이 이미 있어요. 그 계정 비밀번호가 필요해요',
                                      'writer_password_required', 409))
    return PLAN_REFUSE


def _describe_blocker(error: GbrainServerError) -> dict:
    return {'code': error.code, 'error': str(error), 'next_step': find_next_step(error.code),
            **(error.details or {})}
