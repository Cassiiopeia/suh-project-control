"""gbrain 이름·포트·경로 사본 일치 검사 (#213): 원본 config/gbrain_server_config.py
코드로 공유할 수 없는 사본 3곳: nginx.conf, scripts/setup-gbrain-http.ps1 기본값, control_tower/services.yml 감시 주소"""
import re
from pathlib import Path

from config import gbrain_server_config as config

SERVER_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF_PATH = SERVER_ROOT / 'config' / 'nginx.conf'
SETUP_SCRIPT_PATH = SERVER_ROOT / 'scripts' / 'setup-gbrain-http.ps1'
SERVICES_YML_PATH = SERVER_ROOT / 'flask' / 'config' / 'control_tower' / 'services.yml'

PERSONAL_PORT = int(config.GBRAIN_SERVER_URL.rsplit(':', 1)[-1])


def read_text(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def test_nginx_개인_브레인_upstream_과_공개_경로가_설정과_같다():
    nginx_conf = read_text(NGINX_CONF_PATH)

    assert re.search(rf'upstream\s+gbrain_backend\s*\{{\s*server\s+127\.0\.0\.1:{PERSONAL_PORT};', nginx_conf)
    assert f'location = {config.GBRAIN_PERSONAL_MCP_PATH} {{' in nginx_conf


def test_nginx_팀_경로는_설정의_경로_모양과_프로젝트_키를_모두_받는다():
    nginx_conf = read_text(NGINX_CONF_PATH)
    team_location = re.search(r'location ~ \^(/team/\(\?<team_brain_project>(\[[^\]]+\]\[[^\]]+\]\+)\)/mcp)\$', nginx_conf)

    assert team_location, 'nginx 팀 브레인 location 을 찾지 못했어요'
    nginx_project_pattern = re.compile('^' + team_location.group(2) + '$')
    assert config.GBRAIN_TEAM_MCP_PATH_TEMPLATE == '/team/{project}/mcp'
    # 설정 규칙에 맞는 키는 nginx 도 받아야 함 (반대는 map 이 걸러 냄)
    for project in ['ab', 'passql', 'romrom2', 'a' + 'b' * 19]:
        assert re.match(config.GBRAIN_TEAM_PROJECT_PATTERN, project)
        assert nginx_project_pattern.match(project), project


def test_설치_스크립트_기본값이_개인_브레인_설정과_같다():
    setup_script = read_text(SETUP_SCRIPT_PATH)

    assert f'[int]$Port = {PERSONAL_PORT},' in setup_script
    assert f'[string]$ServiceName = "{config.GBRAIN_SERVICE_NAME}",' in setup_script
    assert re.search(rf'\[string\]\$LogPath = "[^"]*\\{re.escape(config.GBRAIN_LOG_FILE_NAME)}"', setup_script)


def test_관제소_감시_주소가_개인_브레인_포트와_같다():
    services_yml = read_text(SERVICES_YML_PATH)

    assert f'http://127.0.0.1:{PERSONAL_PORT}/health' in services_yml
    assert f'# NSSM {config.GBRAIN_SERVICE_NAME}' in services_yml
