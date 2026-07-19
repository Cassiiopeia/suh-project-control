# Chatterbox Multilingual 서빙 이미지 (MIT, 한국어 포함 23개 언어, 0.5B)
# 모델은 첫 기동 시 HF에서 자동 다운로드 -> /root/.cache 볼륨 캐시
# chatterbox-tts가 torch 2.6 계열을 요구 — pip이 어긋난 torchvision을 끌어와
# torchvision::nms 오류로 죽는 것을 막기 위해 마지막에 버전 트리오를 강제 고정한다
FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

RUN pip install --no-cache-dir chatterbox-tts fastapi uvicorn python-multipart && \
    pip install --no-cache-dir --force-reinstall --no-deps \
      torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 \
      --index-url https://download.pytorch.org/whl/cu124

WORKDIR /app
COPY server.py /app/server.py

EXPOSE 7802
CMD ["python3", "server.py"]
