# suh-ai-server Flask Docker 배포 전환 설계

- 날짜: 2026-07-13
- 상태: 승인됨
- 스코프: suh-ai-server Flask 앱의 컨테이너화 및 CI/CD 배포 방식 전환

## 배경 / 문제

현재 배포는 GitHub Actions에서 SCP로 전체 파일을 Windows 서버(`C:\AI\suh-ai-server`)에
복사한 뒤, PowerShell 스크립트 3개(`deploy-init.ps1`, `deploy-nginx.ps1`, `deploy-flask.ps1`)를
순차 실행하는 구조다. 매 배포마다 `pip install`이 돌고, NSSM 윈도우 서비스를 stop/start하며,
nginx.conf에 API 키를 sed로 주입/백업/복원하는 등 절차가 조잡하고 수동적이다.

목표: **Docker 이미지 빌드 → DockerHub push → 서버에서 pull + 재기동** 으로 배포를 단순화한다.

## 확정된 환경 사실 (2026-07-13 실측)

| 항목 | 값 |
|---|---|
| 배포 서버 | 이 PC (Windows 10 build 19045, 상시 켜짐 + 로그인 유지) |
| WSL2 | 2.7.10.0 설치·정상 |
| Docker Desktop | 28.4.0, WSL2 백엔드. `AutoStart` 설정을 False → **True로 변경 완료** (HKCU Run 키 존재 확인) |
| Ollama | Windows 네이티브 `ollama.exe` v0.30.9, `::11434` 리스닝. **컨테이너 유지 안 함 (네이티브 유지)** |
| 컨테이너→Ollama | `http://host.docker.internal:11434` 실측 HTTP 200 (7ms) — 검증 완료 |
| 현재 Flask | NSSM 서비스 `FlaskOCRService` (Automatic, 포트 5000, Waitress) |
| nginx | 현재 미구동 (포트 11436 리스닝 없음). **이번 스코프 제외** |
| DockerHub | 계정 `cassiiopeia`. 토큰은 채팅에 노출됐으므로 등록 전 재발급 권장 |

## 결정 사항

1. **길 B 확정**: Dockerfile + DockerHub(`docker.io/cassiiopeia/suh-ai-flask`) 배포.
   Flask는 Windows 네이티브 Ollama의 API 도우미이므로 Docker 실익이 제한적임을 안내했으나,
   사용자가 DockerHub pull 배포 방식을 명시적으로 선택.
2. **접근안 A (Push 방식)**: GitHub Actions가 빌드·push 후 SSH로 서버에서
   `docker compose pull && up -d` 실행. (Watchtower 폴링 방식은 관측성 부족으로 기각)
3. **스코프**: Flask만 컨테이너화. nginx/API 키 인증은 후속 작업.
4. **NSSM 제거**: 컨테이너 정상 동작 검증 후 `FlaskOCRService` 중지·삭제 (포트 5000 충돌 방지).
5. **트리거**: `main`/`deploy` push 중 `suh-ai-server/**` 경로 변경 시에만 + `workflow_dispatch`.
6. **태그 전략**: `latest` + `<git-sha>` 이중 태그 (SHA 태그로 롤백 가능).

## 아키텍처

```
[개발자] git push (suh-ai-server/** 변경)
    │
    ▼
[GitHub Actions]
    ├─ Job1 build-and-push: docker buildx build
    │     → push cassiiopeia/suh-ai-flask:latest + :<git-sha>
    └─ Job2 deploy: compose 파일 SCP(1개) → SSH(포트 2023)
          → docker compose pull && docker compose up -d → /health 검증
    │
    ▼
[Windows 서버]
    Docker Desktop (AutoStart)
      └─ [flask 컨테이너] :5000 ──> host.docker.internal:11434 ──> ollama.exe
```

## 변경 내역

### 코드 수정 (기존 동작 무변경)

| 파일 | 변경 |
|---|---|
| `suh-ai-server/flask/config/app_config.py` | `OLLAMA_API_URL = os.getenv('OLLAMA_API_URL', 'http://127.0.0.1:11434')` 추가 |
| `suh-ai-server/flask/service/ocr_service.py` | 생성자 기본값을 `app_config.OLLAMA_API_URL`로 변경 (현재 `127.0.0.1:11434` 하드코딩) |
| `suh-ai-server/flask/service/vision_service.py` | 동일 |

로컬 실행 시 기본값 `127.0.0.1:11434` 유지, 컨테이너에서는 compose가
`host.docker.internal`을 환경변수로 주입.

### 신규 파일

**`suh-ai-server/flask/Dockerfile`**
- `python:3.12-slim` 베이스
- `requirements.txt` 먼저 복사 → `pip install` (레이어 캐시 활용)
- 소스 복사, `EXPOSE 5000`, `CMD ["python", "run.py"]` (Waitress 프로덕션 서버 그대로)

**`suh-ai-server/docker-compose.yml`**
```yaml
services:
  flask:
    image: cassiiopeia/suh-ai-flask:latest
    ports: ["5000:5000"]
    environment:
      - OLLAMA_API_URL=http://host.docker.internal:11434
    restart: always            # 재부팅 시 Docker 기동과 함께 자동 복구
    healthcheck: /health 기반
    volumes:
      - ./logs:/app/logs       # log_router가 읽는 로그 유지
```

### 워크플로우 교체 (`.github/workflows/SUH-AI-PROJECT-CONTROL.yaml`)

- 트리거: `push` (branches: `main`, `deploy` + paths 필터: `suh-ai-server/**`) 및 `workflow_dispatch`
- Job1 `build-and-push`: `docker/login-action` → `docker/build-push-action`,
  태그 `latest` + `${{ github.sha }}`
- Job2 `deploy` (needs Job1): `docker-compose.yml` 1개 파일만 SCP →
  SSH로 `docker compose pull && docker compose up -d` → `/health` 응답 검증
- 삭제되는 스텝: 전체 폴더 SCP, nginx API 키 주입, `deploy-init.ps1`,
  `deploy-nginx.ps1`, `deploy-flask.ps1` 호출 (ps1 파일 자체는 보존)

### GitHub Secrets

| 시크릿 | 상태 |
|---|---|
| `SERVER_HOST` / `SERVER_USER` / `SERVER_PASSWORD` (포트 2023) | 기존 재사용 |
| `DOCKERHUB_USERNAME` | 신규 (`cassiiopeia`) |
| `DOCKERHUB_TOKEN` | 신규. **채팅 노출로 재발급 권장** |

## 전환 절차

1. 로컬 빌드 → 임시 포트로 컨테이너 기동 → `/health` + OCR/Vision 스모크 테스트
2. 통과 시: NSSM `FlaskOCRService` 중지·삭제 → `docker compose up -d` (포트 5000 인계)
3. GitHub Secrets 등록 → 실제 push로 Actions 전 과정 1회 검증

## 롤백

- 이미지 문제: `docker compose down` 후 이전 `<git-sha>` 태그로 기동
- 전면 롤백: NSSM 재등록 (`deploy-flask.ps1` 보존됨 — 서비스 재생성 로직 포함)

## 테스트 계획

- 로컬: 이미지 빌드 성공, 컨테이너 `/health` 200, OCR 엔드포인트 실호출(작은 모델)로
  컨테이너→Ollama 경로 검증
- 배포 후: Actions Job2의 `/health` 검증 스텝 통과 확인, `docker logs`로 기동 로그 확인

## 스코프 제외 (후속)

- nginx 컨테이너화 + API 키 인증 프록시 (사용자: "nginx는 나중에")
- Ollama 컨테이너화 (하지 않음 — GPU/모델 관리상 네이티브 유지)
