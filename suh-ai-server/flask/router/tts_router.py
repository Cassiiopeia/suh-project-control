"""
TTS router — 음성 합성 API + 엔진 수명주기 제어
관리 페이지(/admin/tts)가 사용하고, /tts는 외부 클라이언트에도 공개된다
"""
import logging

from flask import Blueprint, Response, jsonify, request

from config.tts_config import TTS_ENGINES
from service import audit_service
from service.audit_service import AuditCategory, AuditAction
from service.tts.adapters import get_adapter
from service.tts.voice_store import voice_store
from service.tts_service import TtsService

logger = logging.getLogger(__name__)

tts_bp = Blueprint('tts', __name__)
tts_service = TtsService()

MAX_TTS_TEXT = 500  # 장문 요청의 GPU 장기 점유 방지

_CONTROL_AUDIT_ACTIONS = {
    'install': AuditAction.TTS_INSTALL,
    'start': AuditAction.TTS_START,
    'stop': AuditAction.TTS_STOP,
}


def _builtin_voice_ids():
    return {v['id'] for spec in TTS_ENGINES.values() for v in spec['voices']}


def _client_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr or '')


@tts_bp.route('/tts/engines', methods=['GET'])
def engines_state():
    """엔진 카탈로그 + 상태 (관리 페이지 폴링용)"""
    return jsonify({'success': True, 'engines': tts_service.get_engines_state()}), 200


@tts_bp.route('/tts/engines/<engine_id>/<action>', methods=['POST'])
def engine_control(engine_id, action):
    """엔진 설치/시작/중지 — 관리 행위라 감사로그 기록"""
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    if action not in _CONTROL_AUDIT_ACTIONS:
        return jsonify({'error': f'알 수 없는 동작: {action}'}), 404
    try:
        getattr(tts_service, action)(engine_id)
    except ValueError as e:  # 미설치 상태 start, 중복 install 등
        return jsonify({'error': str(e)}), 409
    except Exception as e:
        logger.error(f"TTS engine {action} failed ({engine_id}): {str(e)}")
        return jsonify({'error': str(e)}), 500
    audit_service.record(AuditCategory.TTS, _CONTROL_AUDIT_ACTIONS[action],
                         _client_ip(), {'engine': engine_id})
    return jsonify({'success': True, 'engines': tts_service.get_engines_state()}), 200


@tts_bp.route('/tts/engines/<engine_id>/logs', methods=['GET'])
def engine_logs(engine_id):
    """컨테이너 로그 tail — 설치·모델 다운로드 진행 확인용"""
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    try:
        return jsonify({'success': True, 'logs': tts_service.logs(engine_id)}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@tts_bp.route('/tts/voices', methods=['GET'])
def list_voices():
    """내장 + 사용자 등록 보이스 통합 목록 (공개)"""
    voices = [{'id': v['id'], 'name': v['name'], 'engine': engine_id, 'builtin': True}
              for engine_id, spec in TTS_ENGINES.items() for v in spec['voices']]
    voices += [{'id': v['id'], 'name': v['name'], 'engine': 'cosyvoice', 'builtin': False,
                'created_at': v['created_at']} for v in voice_store.list()]
    return jsonify({'success': True, 'voices': voices}), 200


@tts_bp.route('/tts/voices', methods=['POST'])
def add_voice():
    """보이스 클로닝용 레퍼런스 음성 등록 (multipart: name + file)"""
    name = (request.form.get('name') or '').strip()
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'file(WAV)이 필요합니다'}), 400
    try:
        entry = voice_store.add(name, file.read())
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    audit_service.record(AuditCategory.TTS, AuditAction.TTS_VOICE_ADD, _client_ip(),
                         {'voice_id': entry['id'], 'name': entry['name']})
    logger.info(f"TTS voice added: {entry['id']} ({entry['name']})")
    return jsonify({'success': True, 'voice': entry}), 200


@tts_bp.route('/tts/voices/<voice_id>', methods=['DELETE'])
def delete_voice(voice_id):
    """사용자 등록 보이스 삭제 — 내장 보이스는 삭제 불가"""
    if voice_id in _builtin_voice_ids():
        return jsonify({'error': '내장 보이스는 삭제할 수 없습니다'}), 403
    try:
        voice_store.delete(voice_id)
    except KeyError:
        return jsonify({'error': f'보이스를 찾을 수 없습니다: {voice_id}'}), 404
    audit_service.record(AuditCategory.TTS, AuditAction.TTS_VOICE_DELETE, _client_ip(),
                         {'voice_id': voice_id})
    return jsonify({'success': True, 'voice_id': voice_id}), 200


@tts_bp.route('/tts', methods=['POST'])
def synthesize():
    """텍스트 → WAV. engine 생략 시 실행 중 엔진 사용.
    JSON 또는 multipart 지원 — multipart에 prompt_wav를 첨부하면 등록 없이 원샷 클로닝"""
    ref_wav = None
    if request.content_type and 'multipart/form-data' in request.content_type:
        data = request.form
        prompt = request.files.get('prompt_wav')
        ref_wav = prompt.read() if prompt else None
    else:
        data = request.get_json(silent=True) or {}
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'text is required'}), 400
    if len(text) > MAX_TTS_TEXT:
        return jsonify({'error': f'텍스트는 {MAX_TTS_TEXT}자 이하여야 합니다 (현재 {len(text)}자)'}), 400
    engine_id = data.get('engine') or tts_service.get_running_engine()
    if not engine_id:
        return jsonify({'error': '실행 중인 TTS 엔진이 없습니다'}), 503
    if engine_id not in TTS_ENGINES:
        return jsonify({'error': f'알 수 없는 엔진: {engine_id}'}), 404
    voice = data.get('voice') or TTS_ENGINES[engine_id]['voices'][0]['id']
    try:
        speed = float(data.get('speed', 1.0))
    except (TypeError, ValueError):
        return jsonify({'error': 'speed must be a number'}), 400
    try:
        wav = get_adapter(engine_id).synthesize(text, voice, speed, ref_wav=ref_wav)
    except Exception as e:
        logger.error(f"TTS synth failed ({engine_id}): {str(e)}")
        return jsonify({'error': f'합성 실패: {str(e)}'}), 503
    return Response(wav, mimetype='audio/wav')
