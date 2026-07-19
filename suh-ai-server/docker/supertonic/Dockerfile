# Supertonic 서빙 이미지 — CPU 전용 ONNX 초경량 TTS (한국어 포함 31개 언어)
# GPU 무점유라 GPU 엔진(CosyVoice 등)과 상시 동시 가동 가능
FROM python:3.11-slim

RUN pip install --no-cache-dir 'supertonic[serve]'

# 모델은 첫 기동 시 HF에서 자동 다운로드 → /root/.cache 볼륨에 캐시
EXPOSE 7788
CMD ["supertonic", "serve", "--host", "0.0.0.0", "--port", "7788"]
