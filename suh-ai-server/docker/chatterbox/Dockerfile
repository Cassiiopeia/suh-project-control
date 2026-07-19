# Chatterbox Multilingual 서빙 이미지 (MIT, 한국어 포함 23개 언어, 0.5B)
# 모델은 첫 기동 시 HF에서 자동 다운로드 -> /root/.cache 볼륨 캐시
FROM pytorch/pytorch:2.5.1-cuda12.1-cudnn9-runtime

RUN pip install --no-cache-dir chatterbox-tts fastapi uvicorn python-multipart

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 7802
CMD ["python3", "server.py"]
