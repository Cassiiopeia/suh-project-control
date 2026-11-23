"""
gbrain HTTP 서버 1개의 위치 정보: 개인 브레인(gbrain-http) 1개 + 팀 브레인(gbrain-team-<project>) N개
상태·로그·제어(GbrainServerService)와 토큰(GbrainTokenService)이 이 값으로 대상 서버를 고름
"""
import os
from dataclasses import dataclass

from config import gbrain_server_config as config

# 개인 브레인 id (토큰 API ?brain= 기본값)
PERSONAL_BRAIN_ID = 'personal'
# 토큰 권한 선택지 2개 (화면 라디오 값과 같음): 개인 기본 읽기+쓰기, 팀 기본 읽기 전용
READ_WRITE_SCOPE_PRESET = 'read_write'
READ_ONLY_SCOPE_PRESET = 'read_only'


@dataclass(frozen=True)
class GbrainInstance:
    brain_id: str                 # personal 또는 팀 프로젝트 키 (예: passql)
    label: str                    # 화면 표시 이름
    service_name: str             # NSSM 서비스 이름
    port: int                     # 127.0.0.1 내부 포트
    gbrain_home: str | None       # None: 개인 GBRAIN_HOME (테스트 monkeypatch 반영 위해 호출 시 읽음)
    admin_token_file: str | None  # None: 개인 GBRAIN_ADMIN_TOKEN_FILE (위와 같음)
    log_path: str
    mcp_url: str                  # 기기·팀원에게 줄 공개 MCP 주소
    mcp_server_name: str          # claude mcp add 이름 (gbrain / gbrain-<project>)
    database_name: str | None = None
    writer_role: str | None = None
    is_team: bool = False

    @property
    def server_url(self) -> str:
        return f'http://127.0.0.1:{self.port}'

    @property
    def health_url(self) -> str:
        return self.server_url + '/health'

    @property
    def default_scope_preset(self) -> str:
        # 팀원 토큰은 읽기 전용이 기본, 개인 기기는 읽기+쓰기 (#207)
        return READ_ONLY_SCOPE_PRESET if self.is_team else READ_WRITE_SCOPE_PRESET


# ---------- 팀 브레인 이름 규칙 (프로젝트 키 > 이름, 여기 한 곳에서만 만듦) ----------
def to_team_service_name(project: str) -> str:
    return config.GBRAIN_TEAM_SERVICE_PREFIX + project


def to_team_mcp_server_name(project: str) -> str:
    return config.GBRAIN_TEAM_MCP_SERVER_PREFIX + project


def to_team_mcp_url(project: str) -> str:
    return config.GBRAIN_PUBLIC_BASE_URL + config.GBRAIN_TEAM_MCP_PATH_TEMPLATE.format(project=project)


def to_team_database_name(project: str) -> str:
    return config.GBRAIN_TEAM_DATABASE_PREFIX + project


def to_team_writer_role(project: str) -> str:
    return project + config.GBRAIN_TEAM_WRITER_ROLE_SUFFIX


def to_team_admin_token_file(project: str) -> str:
    return os.path.join(config.GBRAIN_SECRETS_DIR, to_team_service_name(project) + config.GBRAIN_TEAM_ADMIN_TOKEN_FILE_SUFFIX)


def build_personal_instance() -> GbrainInstance:
    port = int(config.GBRAIN_SERVER_URL.rsplit(':', 1)[-1].rstrip('/'))
    return GbrainInstance(
        brain_id=PERSONAL_BRAIN_ID, label='개인 브레인', service_name=config.GBRAIN_SERVICE_NAME, port=port,
        gbrain_home=None, admin_token_file=None, log_path=config.GBRAIN_LOG_PATH,
        mcp_url=config.GBRAIN_PUBLIC_MCP_URL, mcp_server_name=config.GBRAIN_PERSONAL_MCP_SERVER_NAME,
        database_name=config.GBRAIN_PERSONAL_DATABASE_NAME)


def describe_token_page_settings() -> dict:
    """관리 화면 토큰 카드 기준 값 (JS 는 이 값만 씀, 사본 상수 없음)"""
    personal_instance = build_personal_instance()
    return {
        'personal_brain_id': PERSONAL_BRAIN_ID,
        'personal_mcp_url': personal_instance.mcp_url,
        'personal_mcp_server_name': personal_instance.mcp_server_name,
        'read_write_scope_preset': READ_WRITE_SCOPE_PRESET,
        'read_only_scope_preset': READ_ONLY_SCOPE_PRESET,
        'personal_default_scope_preset': READ_WRITE_SCOPE_PRESET,
        'team_default_scope_preset': READ_ONLY_SCOPE_PRESET,
    }


def build_team_instance(project: str, port: int, database_name: str, writer_role: str) -> GbrainInstance:
    """팀 프로젝트 키 > 서비스·폴더·토큰·로그·공개 주소 (모두 이름 규칙으로 정해짐)"""
    team_home = os.path.join(config.GBRAIN_TEAM_ROOT, project)
    return GbrainInstance(
        brain_id=project, label=f'{project} 팀 브레인',
        service_name=to_team_service_name(project), port=port,
        gbrain_home=team_home,
        admin_token_file=to_team_admin_token_file(project),
        log_path=os.path.join(team_home, 'logs', config.GBRAIN_LOG_FILE_NAME),
        mcp_url=to_team_mcp_url(project),
        mcp_server_name=to_team_mcp_server_name(project),
        database_name=database_name, writer_role=writer_role, is_team=True)
