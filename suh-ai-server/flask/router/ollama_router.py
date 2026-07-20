"""
Ollama test router — 관리자 Structured Output 테스트 페이지 전용
외부 호출자는 nginx가 Ollama를 직접 프록시하므로 이 엔드포인트를 쓸 필요 없음
"""
from flask import Blueprint, request, jsonify
from service.ollama_service import OllamaService
from service.audit_service import AuditCategory, AuditAction
from util.audit_helper import audited, set_audit_detail
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
        auto_unload = bool(data.get('auto_unload', False))

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
            auto_unload=auto_unload,
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


@ollama_bp.route('/ollama/benchmark/batch', methods=['POST'])
@audited(AuditCategory.MODEL, AuditAction.BENCHMARK_CREATE)
def create_benchmark_batch():
    """벤치마크 마스터 배치 생성"""
    try:
        data = request.get_json() or {}
        prompt = data.get('prompt', '').strip()
        system = data.get('system', '').strip() or None
        
        try:
            temperature = float(data.get('temperature', 0.0))
        except (TypeError, ValueError):
            return jsonify({'error': 'temperature must be a number'}), 400
            
        format_mode = data.get('format_mode', 'none')
        schema_definition = data.get('schema_definition') or None

        if not prompt:
            return jsonify({'error': 'prompt is required'}), 400

        # 감사로그 상세 정보 적재
        set_audit_detail({
            'prompt_summary': prompt[:100] + '...' if len(prompt) > 100 else prompt,
            'format_mode': format_mode,
            'temperature': temperature
        })

        batch_id = ollama_service.create_benchmark_batch(
            prompt=prompt,
            system_prompt=system,
            temperature=temperature,
            format_mode=format_mode,
            schema_definition=schema_definition
        )
        return jsonify({'success': True, 'batch_id': batch_id}), 200
    except Exception as e:
        logger.error(f"Failed to create benchmark batch: {str(e)}")
        return jsonify({'error': str(e)}), 500


@ollama_bp.route('/ollama/benchmark/result', methods=['POST'])
@audited(AuditCategory.MODEL, AuditAction.BENCHMARK_RESULT)
def upsert_benchmark_result():
    """단일 모델 실행 결과 UPSERT"""
    try:
        data = request.get_json() or {}
        batch_id = data.get('batch_id')
        model_name = data.get('model_name')
        status = data.get('status')
        response_content = data.get('response_content')
        metrics = data.get('metrics')
        schema_compliance = data.get('schema_compliance', 'N/A')

        if not batch_id or not model_name or not status:
            return jsonify({'error': 'batch_id, model_name, and status are required'}), 400

        # 감사로그 상세 정보 적재
        set_audit_detail({
            'batch_id': batch_id,
            'model_name': model_name,
            'status': status,
            'schema_compliance': schema_compliance
        })

        ok = ollama_service.upsert_benchmark_result(
            batch_id=int(batch_id),
            model_name=model_name,
            status=status,
            response_content=response_content,
            metrics=metrics,
            schema_compliance=schema_compliance
        )
        return jsonify({'success': ok}), 200
    except Exception as e:
        logger.error(f"Failed to upsert benchmark result: {str(e)}")
        return jsonify({'error': str(e)}), 500


@ollama_bp.route('/ollama/benchmark/history', methods=['GET'])
def list_benchmark_history():
    """최근 15개 벤치마크 마스터 이력 목록 조회"""
    try:
        batches = ollama_service.list_benchmark_history(limit=15)
        return jsonify({'success': True, 'batches': batches}), 200
    except Exception as e:
        logger.error(f"Failed to list benchmark history: {str(e)}")
        return jsonify({'error': str(e)}), 500


@ollama_bp.route('/ollama/benchmark/history/<int:batch_id>', methods=['GET'])
def get_benchmark_batch_details(batch_id):
    """특정 배치 세부 지표 및 응답 JSON 로드 (Lazy Loading)"""
    try:
        results = ollama_service.get_benchmark_batch_details(batch_id)
        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        logger.error(f"Failed to load details for batch {batch_id}: {str(e)}")
        return jsonify({'error': str(e)}), 500


@ollama_bp.route('/ollama/status', methods=['GET'])
def get_ollama_status():
    """로컬 Ollama 서비스의 구동 여부 및 현재 VRAM 로드된 모델 목록 조회"""
    try:
        is_running = ollama_service.is_ollama_running()
        loaded = ollama_service.get_vram_loaded_models() if is_running else []
        # 실측 VRAM과 고아 런너 수를 함께 내려 /api/ps에 안 잡히는 유령 점유를 가시화한다
        gpu = ollama_service.get_gpu_vram_usage()
        orphan_runners = ollama_service.get_orphan_runner_count() if is_running else 0
        return jsonify({
            'success': True,
            'running': is_running,
            'loaded_models': loaded,
            'gpu': gpu,
            'orphan_runners': orphan_runners
        }), 200
    except Exception as e:
        logger.error(f"Ollama status check failed: {str(e)}")
        return jsonify({'success': False, 'running': False, 'loaded_models': [],
                        'gpu': {'available': False}, 'orphan_runners': 0}), 500


@ollama_bp.route('/ollama/control/<action>', methods=['POST'])
@audited(AuditCategory.MODEL)
def control_ollama_daemon(action):
    """Ollama 프로세스 제어 (시작, 정지, 재시작 및 VRAM 강제 비우기)"""
    from util.audit_helper import set_audit_action
    
    if action not in ('start', 'stop', 'restart', 'unload'):
        return jsonify({'error': 'Invalid action'}), 400

    try:
        data = request.get_json() or {}
        model_name = data.get('model') or None

        # 감사 액션 및 디테일 매핑 설정
        if action == 'start':
            set_audit_action(AuditAction.OLLAMA_START)
        elif action == 'stop':
            set_audit_action(AuditAction.OLLAMA_STOP)
        elif action == 'restart':
            set_audit_action(AuditAction.OLLAMA_RESTART)
        elif action == 'unload':
            set_audit_action(AuditAction.OLLAMA_UNLOAD)
            set_audit_detail({'model': model_name or 'ALL'})

        # 서비스 비즈니스 레이어 구동
        ok = False
        summary = ""
        if action == 'start':
            ok = ollama_service.start_ollama_daemon()
            summary = "Ollama 서비스 데몬을 안전 기동하였습니다."
        elif action == 'stop':
            ok = ollama_service.stop_ollama_daemon()
            summary = "Ollama 서비스를 강제 중지하였습니다."
        elif action == 'restart':
            ok = ollama_service.restart_ollama_daemon()
            summary = "Ollama 서비스를 완전 재기동하였습니다."
        elif action == 'unload':
            ok = ollama_service.unload_vram_model(model_name)
            summary = f"VRAM 모델 [{model_name or '전체'}] 언로드 메모리 반환 완료"

        return jsonify({'success': ok, 'summary': summary}), 200
    except Exception as e:
        logger.error(f"Ollama daemon control failed ({action}): {str(e)}")
        return jsonify({'error': str(e)}), 500


@ollama_bp.route('/ollama/logs', methods=['GET'])
def get_ollama_logs():
    """Ollama server.log 의 실시간 200줄 데이터 뷰 조회"""
    try:
        lines = int(request.args.get('lines', 200))
    except ValueError:
        return jsonify({'error': 'lines must be an integer'}), 400

    try:
        log_file = ollama_service.get_ollama_log_path()
        logs = ollama_service.read_ollama_logs(lines)
        return jsonify({
            'success': True,
            'exists': bool(log_file),
            'log_file': log_file or '스캔된 Ollama 설치 경로 없음',
            'logs': logs
        }), 200
    except Exception as e:
        logger.error(f"Ollama log read failed: {str(e)}")
        return jsonify({'error': str(e)}), 500
