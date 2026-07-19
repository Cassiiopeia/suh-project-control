"""
Model management router — HF 검색·다운로드(pull)·설치 목록·삭제
관리 페이지(/admin/models)가 사용. 텍스트 테스트는 /ollama/chat, 이미지 테스트는 /ocr/* 재사용.
"""
from flask import Blueprint, jsonify, request
from service.download_queue_service import DownloadQueueService
from service.model_service import ModelService
import logging

logger = logging.getLogger(__name__)

model_bp = Blueprint('model', __name__)
model_service = ModelService()
queue_service = DownloadQueueService()


@model_bp.route('/models/installed', methods=['GET'])
def installed_models():
    """설치된 Ollama 모델 목록 (vision capability 포함)"""
    try:
        models = model_service.list_installed_models()
        return jsonify({'success': True, 'models': models}), 200
    except Exception as e:
        logger.error(f"Installed model list failed: {str(e)}")
        return jsonify({'error': f'Ollama connection failed: {str(e)}'}), 500


@model_bp.route('/models/installed', methods=['DELETE'])
def delete_model():
    """설치된 모델 삭제 — 모델명에 /·:가 있어 query parameter 사용"""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name query parameter is required'}), 400
    try:
        model_service.delete_model(name)
        logger.info(f"Model deleted: {name}")
        return jsonify({'success': True, 'name': name}), 200
    except Exception as e:
        logger.error(f"Model delete failed ({name}): {str(e)}")
        return jsonify({'error': f'Model delete failed: {str(e)}'}), 500


@model_bp.route('/models/search', methods=['GET'])
def search_models():
    """HF 허브 GGUF 모델 검색"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'q query parameter is required'}), 400
    try:
        results = model_service.search_hf_models(query)
        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        logger.error(f"HF search failed ({query}): {str(e)}")
        return jsonify({'error': f'HF search failed: {str(e)}'}), 500


@model_bp.route('/models/ollama/search', methods=['GET'])
def search_ollama():
    """Ollama 라이브러리 검색 — ollama.com 파싱 (공식 API 없음)"""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'q query parameter is required'}), 400
    try:
        results = model_service.search_ollama_models(query)
        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        logger.error(f"Ollama search failed ({query}): {str(e)}")
        return jsonify({'error': f'Ollama search failed: {str(e)}'}), 500


@model_bp.route('/models/ollama/tags', methods=['GET'])
def ollama_tags():
    """Ollama 모델의 설치 가능한 태그(변형) 목록"""
    name = request.args.get('name', '').strip()
    if not name:
        return jsonify({'error': 'name query parameter is required'}), 400
    try:
        tags = model_service.list_ollama_tags(name)
        return jsonify({'success': True, 'name': name, 'tags': tags}), 200
    except Exception as e:
        logger.error(f"Ollama tag list failed ({name}): {str(e)}")
        return jsonify({'error': f'Ollama tag list failed: {str(e)}'}), 500


@model_bp.route('/models/hf/files', methods=['GET'])
def hf_files():
    """HF 레포의 GGUF 파일(양자화별) 목록"""
    repo = request.args.get('repo', '').strip()
    if not repo:
        return jsonify({'error': 'repo query parameter is required'}), 400
    try:
        files = model_service.list_hf_gguf_files(repo)
        return jsonify({'success': True, 'repo_id': repo, 'files': files}), 200
    except PermissionError as e:
        return jsonify({'error': str(e)}), 403
    except Exception as e:
        logger.error(f"HF file list failed ({repo}): {str(e)}")
        return jsonify({'error': f'HF file list failed: {str(e)}'}), 500


@model_bp.route('/models/queue', methods=['POST'])
def enqueue_download():
    """모델 다운로드 큐 추가 — 워커가 순차 실행하므로 브라우저를 닫아도 진행된다"""
    data = request.get_json(silent=True) or {}
    name = data.get('name', '').strip() if isinstance(data.get('name'), str) else ''
    if not name:
        return jsonify({'error': 'name is required'}), 400
    try:
        queue_service.enqueue(name)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409
    logger.info(f"Model queued: {name}")
    return jsonify({'success': True, 'queue': queue_service.get_state()}), 200


@model_bp.route('/models/queue', methods=['GET'])
def queue_state():
    """다운로드 큐 상태 조회 (프론트 폴링용)"""
    return jsonify({'success': True, 'queue': queue_service.get_state()}), 200


@model_bp.route('/models/queue/<item_id>', methods=['DELETE'])
def cancel_download(item_id):
    """대기 항목 제거 또는 진행 중 다운로드 취소"""
    try:
        result = queue_service.cancel(item_id)
    except KeyError:
        return jsonify({'error': '해당 항목을 찾을 수 없습니다'}), 404
    logger.info(f"Model queue cancel: {item_id} -> {result}")
    return jsonify({'success': True, 'result': result}), 200
