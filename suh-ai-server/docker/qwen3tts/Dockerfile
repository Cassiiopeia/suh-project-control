# Qwen3-TTS 0.6B CustomVoice 서빙 이미지 (Apache-2.0, 한국어 화자 Sohee 내장)
# 모델은 첫 기동 시 HF에서 자동 다운로드 -> /root/.cache 볼륨 캐시
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

RUN pip install --no-cache-dir qwen-tts fastapi uvicorn soundfile

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 7801
CMD ["python3", "server.py"]
