# =========================================
# TTS 엔진 사전준비 — GPU 패스스루 검증 + 모델 캐시 볼륨 생성
# =========================================
# TTS는 부가 기능이므로 어떤 실패도 본 배포를 막지 않는다 (경고 로그 후 exit 0)

Write-Host "=== [deploy-tts] TTS 사전준비 시작 ==="

# 1. Docker 데몬 확인
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[deploy-tts] WARN: Docker 데몬이 응답하지 않습니다 - Docker Desktop 상태 확인 필요. 건너뜁니다."
    exit 0
}

# 2. 모델 캐시 볼륨 (이미 있으면 no-op)
docker volume create suh-tts-models | Out-Null
Write-Host "[deploy-tts] 모델 캐시 볼륨 suh-tts-models 준비 완료"

# 3. GPU 패스스루 검증 — 실패하면 TTS 컨테이너가 GPU를 못 쓴다는 뜻
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
if ($LASTEXITCODE -ne 0) {
    Write-Host "[deploy-tts] WARN: GPU 패스스루 실패 - NVIDIA 드라이버의 WSL2 지원(최신 Game Ready/Studio 드라이버) 확인 필요"
    exit 0
}

Write-Host "=== [deploy-tts] 완료: GPU 패스스루 정상 ==="
exit 0
