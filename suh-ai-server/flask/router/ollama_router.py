"""
Ollama test router — 관리자 Structured Output 테스트 페이지 전용
외부 호출자는 nginx가 Ollama를 직접 프록시하므로 이 엔드포인트를 쓸 필요 없음
"""
from flask import Blueprint, request, jsonify
from service.ollama_service import OllamaService
import logging

logger = logging.getLogger(__name__)

ollama_bp = Blueprint('ollama', __name__)
ollama_service = OllamaService()


@ollama_bp.route('/ollama/models', methods=['GET'])
def list_models():
    """
    설치된 Ollama 모델 목록

    Response:
    {
        "success": true,
        "models": [{"name": "gemma3:4b", "size": 3338801718, "parameter_size": "4.3B", "family": "gemma3"}]
    }
    """
    try:
        models = ollama_service.list_models()
        return jsonify({'success': True, 'models': models}), 200
    except Exception as e:
        logger.error(f"Ollama model list failed: {str(e)}")
        return jsonify({'error': f'Ollama connection failed: {str(e)}'}), 500


@ollama_bp.route('/ollama/chat', methods=['POST'])
def chat():
    """
    Structured Outputs 테스트 chat 실행

    Request Body:
    {
        "model": "gemma3:4b",              # Required
        "prompt": "...",                    # Required
        "system": "...",                    # Optional
        "temperature": 0,                   # Optional (default 0)
        "format": null | "json" | {...}     # Optional — JSON Schema 객체면 구조 강제
    }

    Response:
    {
        "success": true,
        "content": "{...}",
        "model": "gemma3:4b",
        "metrics": {"total_duration_ms": 2100, "eval_count": 71, "tokens_per_second": 37.4, ...}
    }
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({'error': 'JSON body required'}), 400

        model = data.get('model', '').strip() if isinstance(data.get('model'), str) else ''
        prompt = data.get('prompt', '').strip() if isinstance(data.get('prompt'), str) else ''

        if not model:
            return jsonify({'error': 'model is required'}), 400
        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400

        format_spec = data.get('format')
        if format_spec is not None and format_spec != 'json' and not isinstance(format_spec, dict):
            return jsonify({'error': "format must be null, \"json\", or a JSON Schema object"}), 400

        system = data.get('system') or None

        try:
            temperature = float(data.get('temperature', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'temperature must be a number'}), 400

        result = ollama_service.chat(
            model=model,
            prompt=prompt,
            system=system,
            temperature=temperature,
            format_spec=format_spec,
        )

        logger.info(f"Ollama chat completed (model={model})")

        return jsonify({
            'success': True,
            'content': result['content'],
            'model': model,
            'metrics': result['metrics'],
        }), 200

    except Exception as e:
        logger.error(f"Ollama chat error: {str(e)}")
        return jsonify({'error': f'Ollama chat failed: {str(e)}'}), 500
