"""admin 템플릿 경로 회귀 테스트

`root`는 페이지 깊이에 따른 상대경로 프리픽스(`.` 또는 `..`)이며 이미
/api/flask 까지 거슬러 올라간 값이다. 여기에 /api/flask 나 /admin 을 다시
붙이면 경로가 중복돼 404(카드 링크) 또는 401(스웨거 iframe)이 난다.
실측: /api/flask/admin/admin/palworld → 404,
      /api/flask/api/flask/docs/swagger/ → 401
"""
import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates' / 'admin'


def _read(name):
    return (TEMPLATES / name).read_text(encoding='utf-8')


def test_no_template_duplicates_api_flask_prefix():
    """{{ root }} 뒤에 /api/flask 를 또 붙이면 /api/flask/api/flask/... 가 된다"""
    offenders = []
    for path in TEMPLATES.glob('*.html'):
        text = path.read_text(encoding='utf-8')
        if re.search(r'\{\{\s*root\s*\}\}/api/flask', text):
            offenders.append(path.name)
    assert not offenders, f"root 뒤 /api/flask 중복: {offenders}"


def test_dashboard_cards_do_not_duplicate_admin_segment():
    """대시보드는 /admin 에 있으므로 ./admin/X 는 /admin/admin/X 로 중복된다"""
    text = _read('dashboard.html')
    assert './admin/' not in text, "대시보드 카드 링크에 ./admin/ 중복이 남아 있다"


def test_dashboard_cards_point_at_sibling_pages():
    """카드 링크는 형제 경로(./palworld 등)여야 하며, 사이드바 메뉴를 모두 덮어야 한다"""
    text = _read('dashboard.html')
    sidebar = set(re.findall(r'\{\{ root \}\}/admin/([a-z-]+)', _read('base.html')))
    assert sidebar, "사이드바 링크를 하나도 찾지 못했다 — 파싱 규칙 확인 필요"
    for page in sorted(sidebar):
        assert f'href="./{page}"' in text, f"카드 링크 누락/오류: {page}"


def test_dashboard_service_control_covers_all_controllable_services():
    """서비스 제어 카드는 제어 API가 있는 서비스를 모두 다뤄야 한다"""
    js = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'dashboard.js').read_text(encoding='utf-8')
    for kind in ('palworld', 'ollama', 'sunshine'):
        assert f"{kind}: function (action)" in js, f"CONTROL_PATH에 {kind} 없음"
        assert f"serviceCard('{kind}'" in js, f"서비스 카드 렌더에 {kind} 없음"


def test_service_control_card_style_matches_other_pages():
    """대시보드 제어부만 작은 버튼·안 보이는 테두리를 쓰면 UI가 어긋난다 (실측 확인)"""
    js = (Path(__file__).resolve().parent.parent / 'static' / 'js' / 'dashboard.js').read_text(encoding='utf-8')
    assert 'btn btn-xs' not in js, "제어 버튼은 다른 페이지와 같은 btn-sm를 쓴다"
    assert 'border border-base-200' not in js, "base-200 테두리는 어두운 테마에서 배경에 묻힌다"


def test_api_docs_iframe_uses_docs_swagger():
    text = _read('api_docs.html')
    assert 'src="{{ root }}/docs/swagger/"' in text
    assert '/api/flask/docs/swagger' not in text
