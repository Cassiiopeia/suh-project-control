"""
Admin pages router - DaisyUI 관리자 페이지 렌더링
root: 페이지 깊이에 따른 상대경로 프리픽스 (nginx 프리픽스 뒤에서도 동작)
"""
import os

from flask import Blueprint, render_template

admin_bp = Blueprint('admin', __name__)

# 정적 자산 캐시 버스팅: 템플릿에서 {{ asset('js/palworld.js') }} → 파일 수정시각 토큰.
# <script src="...palworld.js?v={{ asset('js/palworld.js') }}"> 처럼 써서, 배포로 파일이
# 바뀌면 URL이 달라져 브라우저가 새 파일을 받는다(하드리로드 불필요).
# 블루프린트에 붙여 이 페이지들을 서빙하는 어떤 앱에서도 asset()이 정의되게 한다.
_STATIC_ROOT = os.path.join(os.path.dirname(__file__), '..', 'static')


@admin_bp.app_context_processor
def _inject_asset_helper():
    def asset(rel_path):
        try:
            return str(int(os.path.getmtime(os.path.join(_STATIC_ROOT, rel_path))))
        except OSError:
            return '0'
    return {'asset': asset}


@admin_bp.route('/admin', methods=['GET'])
def dashboard():
    """관리 허브 대시보드"""
    return render_template('admin/dashboard.html', root='.', active='dashboard')


@admin_bp.route('/admin/palworld', methods=['GET'])
def palworld():
    """팰월드 서버 관리 페이지"""
    return render_template('admin/palworld.html', root='..', active='palworld')


@admin_bp.route('/admin/audit', methods=['GET'])
def audit():
    """관리 행위 감사로그 페이지"""
    return render_template('admin/audit.html', root='..', active='audit')


@admin_bp.route('/admin/logs', methods=['GET'])
def flask_logs():
    """Flask 서버 로그 페이지"""
    return render_template('admin/logs.html', root='..', active='flask-logs')


@admin_bp.route('/admin/ollama-test', methods=['GET'])
def ollama_test():
    """Ollama Structured Output 테스트 페이지"""
    return render_template('admin/ollama-test.html', root='..', active='ollama-test')


@admin_bp.route('/admin/ollama', methods=['GET'])
def ollama():
    """Ollama 서비스 제어 및 모니터링 페이지"""
    return render_template('admin/ollama.html', root='..', active='ollama')


@admin_bp.route('/admin/models', methods=['GET'])
def models():
    """모델 관리 페이지 (HF 검색·다운로드·벤치마크)"""
    return render_template('admin/models.html', root='..', active='models')


@admin_bp.route('/admin/tts', methods=['GET'])
def tts():
    """TTS 엔진 관리 페이지 (설치·전환·테스트)"""
    return render_template('admin/tts.html', root='..', active='tts')


@admin_bp.route('/admin/api-docs', methods=['GET'])
def api_docs():
    """API 문서 페이지 - Swagger UI를 admin 레이아웃 안에 iframe으로 임베드"""
    return render_template('admin/api_docs.html', root='..', active='api-docs')
