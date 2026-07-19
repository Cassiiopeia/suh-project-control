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
    'supertonic': {
        'name': 'Supertonic',
        'description': '초경량 다국어 TTS (한국어 포함 31개 언어) — CPU 전용이라 GPU 엔진과 동시 가동 가능',
        'image': 'cassiiopeia/suh-tts-supertonic:latest',
        'container': 'suh-tts-supertonic',
        'port': 7788,
        'adapter': 'supertonic',
        'languages': ['ko', 'en', 'ja', 'de', 'fr', 'es'],
        'vram': '0 (CPU)',
        'gpu': False,  # GPU 미사용 — "GPU 1개 실행" 정책의 예외
        'docker_args': ['-v', 'suh-tts-models:/root/.cache'],
        'command': [],
        'voices': [
            {'id': 'F1', 'name': '여성 1'},
            {'id': 'F2', 'name': '여성 2'},
            {'id': 'F3', 'name': '여성 3'},
            {'id': 'M1', 'name': '남성 1'},
            {'id': 'M2', 'name': '남성 2'},
            {'id': 'M3', 'name': '남성 3'},
        ],
    },
    'qwen3tts': {
        'name': 'Qwen3-TTS 0.6B',
        'description': '알리바바 Qwen3-TTS — 한국어 화자(Sohee) 내장, 10개 언어 프리셋 (Apache-2.0)',
        'image': 'cassiiopeia/suh-tts-qwen3:latest',
        'container': 'suh-tts-qwen3',
        'port': 7801,
        'adapter': 'qwen3tts',
        'languages': ['ko', 'en', 'zh', 'ja', 'de', 'fr', 'ru', 'pt', 'es', 'it'],
        'vram': '~3GB',
        'gpu': True,
        'docker_args': ['--gpus', 'all', '-v', 'suh-tts-models:/root/.cache'],
        'command': [],
        'voices': [
            {'id': 'Sohee', 'name': '소희 (한국어 여성)'},
            {'id': 'Vivian', 'name': 'Vivian (여성)'},
            {'id': 'Serena', 'name': 'Serena (여성)'},
            {'id': 'Eric', 'name': 'Eric (남성)'},
            {'id': 'Ryan', 'name': 'Ryan (남성)'},
            {'id': 'Ono_Anna', 'name': 'Ono Anna (일본어 여성)'},
        ],
    },
    'chatterbox': {
        'name': 'Chatterbox Multilingual',
        'description': 'Resemble AI 오픈소스 — 한국어 포함 23개 언어, 기본 보이스 + 원샷 클로닝 (MIT)',
        'image': 'cassiiopeia/suh-tts-chatterbox:latest',
        'container': 'suh-tts-chatterbox',
        'port': 7802,
        'adapter': 'chatterbox',
        'languages': ['ko', 'en', 'ja', 'zh', 'de', 'fr', 'es'],
        'vram': '~4GB',
        'gpu': True,
        'docker_args': ['--gpus', 'all', '-v', 'suh-tts-models:/root/.cache'],
        'command': [],
        'voices': [
            {'id': 'default', 'name': '기본 보이스'},
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
