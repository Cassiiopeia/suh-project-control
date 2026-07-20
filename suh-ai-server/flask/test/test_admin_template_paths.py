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
    """카드 링크는 형제 경로(./palworld 등)여야 한다"""
    text = _read('dashboard.html')
    for page in ('palworld', 'ollama-test', 'models', 'tts', 'api-docs', 'logs'):
        assert f'href="./{page}"' in text, f"카드 링크 누락/오류: {page}"


def test_api_docs_iframe_uses_docs_swagger():
    text = _read('api_docs.html')
    assert 'src="{{ root }}/docs/swagger/"' in text
    assert '/api/flask/docs/swagger' not in text
