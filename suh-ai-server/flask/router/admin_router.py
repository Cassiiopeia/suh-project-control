"""
Admin pages router - DaisyUI 관리자 페이지 렌더링
"""
from flask import Blueprint, render_template

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin', methods=['GET'])
def dashboard():
    """관리 허브 대시보드"""
    return render_template('admin/dashboard.html')


@admin_bp.route('/admin/palworld', methods=['GET'])
def palworld():
    """팰월드 서버 관리 페이지"""
    return render_template('admin/palworld.html')
