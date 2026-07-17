"""
TTS 엔진 어댑터 — 엔진별 API 형식 차이를 공통 인터페이스로 흡수
공통 인터페이스: synthesize(text, voice, speed) -> WAV bytes / health() / voices()
"""
import io
import os
import wave

import requests

from config.tts_config import TTS_ENGINES, TTS_REFS_DIR

# 합성 대기 한도 — 컨테이너 첫 요청은 모델 워밍업으로 오래 걸릴 수 있다
SYNTH_TIMEOUT = 120
HEALTH_TIMEOUT = 3


class TtsAdapter:
    def __init__(self, engine_id: str):
        self.engine = TTS_ENGINES[engine_id]
        self.base_url = f"http://127.0.0.1:{self.engine['port']}"

    def synthesize(self, text: str, voice: str, speed: float) -> bytes:
        raise NotImplementedError

    def health(self) -> bool:
        raise NotImplementedError

    def voices(self) -> list:
        return self.engine['voices']


class KokoroAdapter(TtsAdapter):
    """Kokoro-FastAPI — OpenAI 호환 /v1/audio/speech, WAV 직접 반환"""

    def synthesize(self, text, voice, speed):
        resp = requests.post(
            f'{self.base_url}/v1/audio/speech',
            json={'model': 'kokoro', 'voice': voice, 'input': text,
                  'response_format': 'wav', 'speed': speed},
            timeout=SYNTH_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content

    def health(self):
        try:
            return requests.get(f'{self.base_url}/v1/audio/voices',
                                timeout=HEALTH_TIMEOUT).status_code == 200
        except requests.RequestException:
            return False


class CosyVoiceAdapter(TtsAdapter):
    """CosyVoice fastapi 서버 — cross_lingual 모드로 레퍼런스 화자가 다른 언어를 말하게 한다.
    speed 파라미터는 서버가 미지원이라 무시한다."""

    def synthesize(self, text, voice, speed):
        ref = next((v for v in self.engine['voices'] if v['id'] == voice),
                   self.engine['voices'][0])
        ref_path = os.path.join(TTS_REFS_DIR, ref['file'])
        with open(ref_path, 'rb') as f:
            resp = requests.post(
                f'{self.base_url}/inference_cross_lingual',
                data={'tts_text': text},
                files={'prompt_wav': f},
                timeout=SYNTH_TIMEOUT,
            )
        resp.raise_for_status()
        return self._pcm_to_wav(resp.content, self.engine['sample_rate'])

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int) -> bytes:
        """서버 응답은 헤더 없는 int16 mono PCM — 브라우저 재생을 위해 WAV로 감싼다"""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm)
        return buf.getvalue()

    def health(self):
        try:
            # 전용 헬스 엔드포인트가 없어 FastAPI 자동 문서(/docs)로 대신 확인
            return requests.get(f'{self.base_url}/docs',
                                timeout=HEALTH_TIMEOUT).status_code == 200
        except requests.RequestException:
            return False


_ADAPTER_CLASSES = {'kokoro': KokoroAdapter, 'cosyvoice': CosyVoiceAdapter}


def get_adapter(engine_id: str) -> TtsAdapter:
    return _ADAPTER_CLASSES[TTS_ENGINES[engine_id]['adapter']](engine_id)
