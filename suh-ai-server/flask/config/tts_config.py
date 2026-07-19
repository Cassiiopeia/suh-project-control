"""
TTS 엔진 레지스트리 — 지원 엔진 카탈로그
새 엔진 추가 = 여기에 항목 1개 + service/tts/adapters.py에 어댑터 1개
"""
import os

# 제로샷 레퍼런스 음성 저장 위치 (CosyVoice 레포 Apache-2.0 샘플)
TTS_REFS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'static', 'tts-refs'))

TTS_ENGINES = {
    'cosyvoice': {
        'name': 'CosyVoice2-0.5B',
        'description': '한국어 포함 다국어 TTS — 제로샷 보이스 클로닝 (cross-lingual)',
        'image': 'cassiiopeia/suh-tts-cosyvoice:latest',
        'container': 'suh-tts-cosyvoice',
        'port': 50000,
        'adapter': 'cosyvoice',
        'languages': ['ko', 'en', 'zh', 'ja'],
        'vram': '~5GB',
        # 서버가 헤더 없는 int16 mono PCM을 반환 → 어댑터가 WAV로 감쌀 때 사용.
        # CosyVoice2 출력 샘플레이트 24kHz — 스모크 테스트에서 음높이 이상 시 재확인
        'sample_rate': 24000,
        'docker_args': ['--gpus', 'all', '-v', 'suh-tts-models:/root/.cache'],
        'command': [],  # docker/cosyvoice/Dockerfile의 CMD가 fastapi 서버 기동
        'voices': [
            {'id': 'ref_a', 'name': '기본 보이스 A (중국어 화자)', 'file': 'ref_a.wav'},
            {'id': 'ref_b', 'name': '기본 보이스 B (영어 화자)', 'file': 'ref_b.wav'},
        ],
    },
    'kokoro': {
        'name': 'Kokoro-82M',
        'description': '초경량 영어 TTS — OpenAI 호환 API, VRAM 부담 거의 없음',
        'image': 'ghcr.io/remsky/kokoro-fastapi-gpu:latest',
        'container': 'suh-tts-kokoro',
        'port': 8880,
        'adapter': 'kokoro',
        'languages': ['en'],
        'vram': '~1GB',
        'docker_args': ['--gpus', 'all'],
        'command': [],  # 이미지 기본 CMD 사용
        'voices': [
            {'id': 'af_heart', 'name': '여성 (미국)'},
            {'id': 'am_michael', 'name': '남성 (미국)'},
            {'id': 'bf_emma', 'name': '여성 (영국)'},
        ],
    },
}
