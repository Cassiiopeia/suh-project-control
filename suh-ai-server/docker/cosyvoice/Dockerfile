# CosyVoice fastapi 서빙 이미지 — 공식 runtime Dockerfile 기반, CMD만 명시
# 모델 가중치는 이미지에 굽지 않는다: 첫 기동 시 modelscope가 받아 /root/.cache 볼륨에 캐시
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && \
    apt-get install -y --no-install-recommends git git-lfs unzip g++ && \
    git lfs install && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git /opt/CosyVoice
WORKDIR /opt/CosyVoice
RUN pip3 install --no-cache-dir -r requirements.txt

# Fun-CosyVoice3 전환은 이 env만 교체 (예: iic/Fun-CosyVoice3-0.5B-2512)
ENV MODEL_DIR=iic/CosyVoice2-0.5B
EXPOSE 50000
CMD ["sh", "-c", "python3 runtime/python/fastapi/server.py --port 50000 --model_dir ${MODEL_DIR}"]
