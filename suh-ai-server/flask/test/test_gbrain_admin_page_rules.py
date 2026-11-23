"""관제소 gbrain 화면 규칙 (#213 브라우저 QA 결함 재발 방지): 소스 검사"""
import re
from pathlib import Path

import pytest

FLASK_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = FLASK_ROOT / 'templates' / 'admin' / 'gbrain.html'
SCRIPT_DIRECTORY = FLASK_ROOT / 'static' / 'js'
# 화면 규칙 검사 대상 스크립트 6개: 개인 서버, 토큰 카드, 토큰 결과 창, 팀 브레인 카드, 팀원 카드, 팀원 키 (#221)
GBRAIN_SCRIPT_NAMES = ['gbrain.js', 'gbrain-tokens.js', 'gbrain-token-result.js', 'gbrain-teams.js',
                       'gbrain-members.js', 'gbrain-member-keys.js']


# 화면 본문 + 부분 템플릿 2개 (토큰 대화창, 팀 브레인 대화창)
PARTIAL_TEMPLATE_PATHS = sorted((FLASK_ROOT / 'templates' / 'admin' / 'gbrain').glob('*.html'))


def read_template() -> str:
    return '\n'.join(path.read_text(encoding='utf-8') for path in [TEMPLATE_PATH] + PARTIAL_TEMPLATE_PATHS)


def read_script(script_name: str) -> str:
    return (SCRIPT_DIRECTORY / script_name).read_text(encoding='utf-8')


def test_브레인을_바꾸면_늦게_온_이전_목록_응답을_버린다():
    tokens_script = read_script('gbrain-tokens.js')

    assert 'requestNumber !== latestListRequestNumber' in tokens_script
    # 응답 전까지 발급 버튼 잠금 (이전 브레인 기본 권한으로 발급 방지)
    assert "getElement('token-create-open').disabled = true" in tokens_script


def test_발급_창은_만들_곳과_실제_기본_권한을_보여_준다():
    template = read_template()
    tokens_script = read_script('gbrain-tokens.js')

    assert 'id="token-create-target"' in template
    assert 'data-scope-default-badge="{{ token_page_settings.read_write_scope_preset }}"' in template
    assert 'data-scope-default-badge="{{ token_page_settings.read_only_scope_preset }}"' in template
    assert '(기본,' not in template  # 권한 라벨에 기본값 고정 문구 금지
    assert 'PAGE_SETTINGS.team_default_scope_preset' in tokens_script
    # 창을 연 때의 브레인으로 발급
    assert "brain: getElement('token-create-modal').dataset.brain" in tokens_script


def test_팀_토큰_결과_창은_팀원_안내와_전체_복사를_맨_위에_둔다():
    template = read_template()

    guide_position = template.index('id="token-team-guide"')
    self_install_position = template.index('id="token-self-install"')
    assert guide_position < self_install_position
    assert 'data-copy-target="token-team-guide-text"' in template
    assert '안내 전체 복사' in template
    assert '1:1' in template[guide_position:self_install_position]


def test_결과_창_스크립트가_토큰_카드보다_먼저_로드된다():
    template = read_template()

    assert template.index('gbrain-token-result.js') < template.index('gbrain-tokens.js?')


# 배지를 만드는 스크립트 5개 (결과 창은 배지 없음)
BADGE_SCRIPT_NAMES = ['gbrain.js', 'gbrain-tokens.js', 'gbrain-teams.js', 'gbrain-members.js', 'gbrain-member-keys.js']


@pytest.mark.parametrize('script_name', BADGE_SCRIPT_NAMES)
def test_상태_배지는_줄바꿈되지_않는다(script_name):
    script = read_script(script_name)

    # class="badge ..." 문자열 + className = '...badge...' 대입식 전체
    badge_classes = re.findall(r"""class=\\?"(badge [^"\\]*)\\?\"""", script)
    badge_classes += [expression for expression in re.findall(r"className = ([^;]+);", script) if 'badge' in expression]
    assert badge_classes, f'{script_name}: 배지 생성 코드가 없어요'
    for badge_class in badge_classes:
        assert 'whitespace-nowrap' in badge_class, f'{script_name}: {badge_class}'


def test_개인_gbrain_중지와_재시작은_확인을_받는다():
    server_script = read_script('gbrain.js')

    assert 'CONTROL_CONFIRM_MESSAGES' in server_script
    assert re.search(r'stop:\s*\'gbrain 서버를 중지할까요', server_script)
    assert re.search(r'restart:\s*\'gbrain 서버를 재시작할까요', server_script)


def test_형식_검사_입력칸은_규칙을_title_로_알린다():
    template = read_template()

    for input_tag in re.findall(r'<input[^>]*pattern="[^"]*"[^>]*>', template, re.S):
        assert 'title="' in input_tag, input_tag


@pytest.mark.parametrize('source_name', ['gbrain.html'] + GBRAIN_SCRIPT_NAMES)
def test_화면_문구는_해요체로_쓴다(source_name):
    source = read_template() if source_name == 'gbrain.html' else read_script(source_name)
    # 주석 제외 (HTML·JS)
    visible_source = re.sub(r'<!--.*?-->|/\*.*?\*/|//[^\n]*', '', source, flags=re.S)

    assert not re.search(r'(습니다|합니다|입니다|하세요)', visible_source)


def test_토큰_카드는_서버_설정_값만_쓰고_사본_상수를_두지_않는다():
    tokens_script = read_script('gbrain-tokens.js')
    template = read_template()

    # 개인 브레인 id·MCP 이름·공개 주소·권한 값은 gbrain_instance.describe_token_page_settings 가 원본
    for copied_literal in ["'personal'", "'gbrain'", 'suhsaechan.kr', "'read_write'", "'read_only'"]:
        assert copied_literal not in tokens_script, copied_literal
    assert 'id="gbrain-token-page-settings"' in template
    assert 'https://ai.suhsaechan.kr/mcp' not in template


@pytest.mark.parametrize('script_name', GBRAIN_SCRIPT_NAMES)
def test_공통_함수는_gbrain_page_common_한_곳에만_둔다(script_name):
    script = read_script(script_name)
    template = read_template()

    for duplicated_definition in ['function el(', 'function readJson(', 'function describeFailure(']:
        assert duplicated_definition not in script, f'{script_name}: {duplicated_definition}'
    assert 'window.gbrainPage' in script
    assert template.index('gbrain-page-common.js') < template.index(script_name + '?')


@pytest.mark.parametrize('script_name', GBRAIN_SCRIPT_NAMES)
def test_스크립트가_찾는_요소_id_는_템플릿에_모두_있다(script_name):
    template = read_template()
    base_template = (FLASK_ROOT / 'templates' / 'admin' / 'base.html').read_text(encoding='utf-8')
    element_ids = set(re.findall(r"getElement\('([^']+)'\)", read_script(script_name)))

    assert element_ids, f'{script_name}: getElement 사용이 없어요'
    for element_id in element_ids:
        assert f'id="{element_id}"' in template + base_template, f'{script_name}: #{element_id}'


# 화면으로 나가는 서버 문구 (오류·요약): gbrain 서비스·라우터
BACKEND_MESSAGE_PATHS = sorted((FLASK_ROOT / 'service').glob('gbrain_*.py')) + sorted((FLASK_ROOT / 'router').glob('gbrain_*.py'))


@pytest.mark.parametrize('source_path', BACKEND_MESSAGE_PATHS, ids=lambda path: path.name)
def test_서버가_화면으로_보내는_gbrain_문구도_해요체로_쓴다(source_path):
    for line in source_path.read_text(encoding='utf-8').splitlines():
        if line.strip().startswith('#') or 'logger.' in line:
            continue  # 주석·영어 로그 제외
        for literal in re.findall(r"""['"]([^'"]*)['"]""", line):
            assert not re.search(r'(습니다|합니다|입니다)', literal), f'{source_path.name}: {literal}'
