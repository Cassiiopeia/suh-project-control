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

# 최신 setuptools(82+)는 pkg_resources가 제거되어 일부 패키지 소스 빌드가 깨진다.
# PIP_CONSTRAINT는 pip의 빌드 격리 환경에도 적용되므로 setuptools<81을 전역 강제한다.
RUN echo 'setuptools<81' > /tmp/pip-constraints.txt
ENV PIP_CONSTRAINT=/tmp/pip-constraints.txt
RUN pip3 install --no-cache-dir -U pip wheel 'setuptools<81' && \
    pip3 install --no-cache-dir -r requirements.txt && \
    # deepspeed는 학습 전용인데 transformers가 import 시 CUDA 컴파일을 시도해
    # 컴파일러(nvcc) 없는 runtime 이미지에서 기동이 죽는다 → 추론 이미지에서 제거
    pip3 uninstall -y deepspeed

# Fun-CosyVoice3 전환은 이 env만 교체 (예: iic/Fun-CosyVoice3-0.5B-2512)
ENV MODEL_DIR=iic/CosyVoice2-0.5B
EXPOSE 50000
CMD ["sh", "-c", "python3 runtime/python/fastapi/server.py --port 50000 --model_dir ${MODEL_DIR}"]
