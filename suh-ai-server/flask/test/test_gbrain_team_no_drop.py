"""팀 브레인 흐름 삭제 금지 (#226): 코드·SQL 문장·준비 SQL 파일에 DB·계정·스키마·표 DROP/TRUNCATE 없음, 삭제 호출 없음"""
import inspect
import os
import re

import pytest

from config import gbrain_server_config
from service.ai_db import ai_db_service, pg_team_brain_client
from service.ai_db.pg_team_brain_client import PgTeamBrainClientMixin

FLASK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# 팀 브레인 흐름 파일 (만들기·dry_run·손보기·서버 작업·등록부·라우터)
TEAM_FLOW_FILES = [
    'service/gbrain_team_brain_service.py', 'service/gbrain_team_database_steps.py',
    'service/gbrain_team_database_repair.py', 'service/gbrain_team_dry_run.py', 'service/gbrain_team_errors.py',
    'service/gbrain_team_provisioner.py', 'service/gbrain_team_registry.py', 'service/ai_db/pg_team_brain_client.py',
    'router/gbrain_team_router.py',
]
# 삭제 문장·호출 (대소문자 무시)
FORBIDDEN_PATTERN = re.compile(
    r'\b(drop|truncate)\b|delete_database|delete_role|drop_database|drop_role|_drop_database_quietly'
    r'|_grant_or_drop_role|reset_password|set_password', re.IGNORECASE)
# AiDbService 중 팀 흐름이 부르는 메서드 (삭제·되돌리기 삭제가 섞인 create_database·create_role 은 쓰지 않음)
TEAM_AI_DB_SERVICE_METHODS = ['inspect_team_database', 'inspect_team_writer_role', 'create_team_database',
                              'create_team_writer_role', 'apply_team_writer_grants', 'prepare_gbrain',
                              'get_gbrain_status']
# 준비 SQL 파일에서 허용하는 유일한 DROP: 위험해서 없앤 옛 함수 정리 (#218, 함수 1개)
ALLOWED_OPS_SQL_DROP = 'DROP FUNCTION IF EXISTS ai_db_ops.grant_gbrain_reader(text, text);'


def strip_comments(source: str) -> str:
    """# 주석 줄 제거 (문서 문자열의 한국어 설명은 검사 대상에 남김)"""
    return '\n'.join(line.split('#', 1)[0] if not line.lstrip().startswith(('"', "'")) else line
                     for line in source.splitlines())


@pytest.mark.parametrize('relative_path', TEAM_FLOW_FILES)
def test_팀_브레인_흐름_파일에는_삭제_문장과_삭제_호출이_없다(relative_path):
    with open(os.path.join(FLASK_ROOT, relative_path), encoding='utf-8') as source_stream:
        source = strip_comments(source_stream.read())

    assert not FORBIDDEN_PATTERN.findall(source), f'{relative_path} has a delete statement or call'


def test_팀_PG_클라이언트_문장과_메서드에_삭제가_없다():
    sql_texts = [value for name, value in vars(pg_team_brain_client).items() if name.endswith('_SQL')]
    method_sources = [inspect.getsource(member) for _, member in inspect.getmembers(PgTeamBrainClientMixin,
                                                                                    inspect.isfunction)]

    assert sql_texts and method_sources
    for text in sql_texts + method_sources:
        assert not FORBIDDEN_PATTERN.search(strip_comments(text))


@pytest.mark.parametrize('method_name', TEAM_AI_DB_SERVICE_METHODS)
def test_팀_흐름이_부르는_AI_DB_서비스_메서드에_삭제가_없다(method_name):
    source = inspect.getsource(getattr(ai_db_service.AiDbService, method_name))

    assert not FORBIDDEN_PATTERN.search(strip_comments(source))


def test_준비_SQL_파일의_DROP_은_옛_함수_정리_1개뿐이다():
    with open(gbrain_server_config.GBRAIN_TEAM_OPS_SQL_PATH, encoding='utf-8') as script_stream:
        statements = [line.strip() for line in script_stream if not line.strip().startswith('--')]

    drop_lines = [line for line in statements if re.search(r'\b(drop|truncate)\b', line, re.IGNORECASE)]
    assert drop_lines == [ALLOWED_OPS_SQL_DROP]
