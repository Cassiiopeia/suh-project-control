"""
Admin pages router - DaisyUI 관리자 페이지 렌더링
root: 페이지 깊이에 따른 상대경로 프리픽스 (nginx 프리픽스 뒤에서도 동작)
"""
from flask import Blueprint, render_template

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin', methods=['GET'])
def dashboard():
    """관리 허브 대시보드"""
    return render_template('admin/dashboard.html', root='.', active='dashboard')


@admin_bp.route('/admin/palworld', methods=['GET'])
def palworld():
    """팰월드 서버 관리 페이지"""
    return render_template('admin/palworld.html', root='..', active='palworld')


@admin_bp.route('/admin/logs', methods=['GET'])
def flask_logs():
    """Flask 서버 로그 페이지"""
    return render_template('admin/logs.html', root='..', active='flask-logs')
