"""test_admin_router.py"""
import pytest
from flask import Flask


@pytest.fixture
def client():
    from router.admin_router import admin_bp
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.register_blueprint(admin_bp)
    return app.test_client()


def test_dashboard_returns_200(client):
    resp = client.get('/admin')
    assert resp.status_code == 200


def test_palworld_page_returns_200(client):
    resp = client.get('/admin/palworld')
    assert resp.status_code == 200


def test_logs_page_returns_500_until_task_8(client):
    """admin/logs.html이 아직 없어 500 - Task 8에서 해소되는 의도된 중간 상태"""
    resp = client.get('/admin/logs')
    assert resp.status_code == 500
