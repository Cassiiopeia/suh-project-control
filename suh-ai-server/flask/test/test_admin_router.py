"""test_admin_router.py — 어드민 페이지 렌더 및 no-emoji 검증"""
import os
import re
import pytest
from flask import Flask

EMOJI_RE = re.compile('[\U0001F300-\U0001FAFF☀-➿]')


@pytest.fixture
def client():
    from router.admin_router import admin_bp
    template_dir = os.path.join(os.path.dirname(__file__), '..', 'templates')
    app = Flask(__name__, template_folder=template_dir)
    app.register_blueprint(admin_bp)
    return app.test_client()


def test_dashboard_renders_with_shell(client):
    resp = client.get('/admin')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '대시보드' in body
    assert 'drawer' in body
    assert 'data-lucide' in body


def test_palworld_page_renders_guide_and_tabs(client):
    resp = client.get('/admin/palworld')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '게임 접속 방법' in body
    assert 'palworld-log-viewer' in body
    assert 'confirm-modal' in body


def test_flask_logs_page_renders(client):
    resp = client.get('/admin/logs')
    assert resp.status_code == 200
    assert 'Flask 서버 로그' in resp.get_data(as_text=True)


def test_models_page_renders(client):
    resp = client.get('/admin/models')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert '모델 관리' in body
    assert 'installed-body' in body
    assert 'bench-run' in body
    assert 'delete-modal' in body


def test_tts_page_renders(client):
    resp = client.get('/admin/tts')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'TTS 관리' in body
    assert 'engine-cards' in body
    assert 'tts-run' in body
    assert 'logs-modal' in body


def test_no_emoji_icons_on_any_admin_page(client):
    for path in ('/admin', '/admin/palworld', '/admin/logs', '/admin/models', '/admin/tts'):
        body = client.get(path).get_data(as_text=True)
        match = EMOJI_RE.search(body)
        assert not match, f'{path} 에 이모지가 남아있음: {match.group() if match else ""}'
