📝 현재 문제점
---

- 현재 suh-ai-server Flask 배포는 GitHub Actions에서 SCP로 전체 파일을 Windows 서버에 복사한 뒤 PowerShell 스크립트 3개(`deploy-init.ps1`, `deploy-nginx.ps1`, `deploy-flask.ps1`)를 순차 실행하는 수동적인 구조임
- 매 배포마다 `pip install`이 실행되고, NSSM 윈도우 서비스를 stop/start하며, nginx.conf에 API 키를 sed로 주입/백업/복원하는 등 절차가 복잡하고 깨지기 쉬움
- 배포 환경 재현성이 없어 서버 환경(Python 경로 등)에 의존적임

🛠️ 해결 방안 / 제안 기능
---

- Flask 앱을 Docker 이미지로 빌드하여 DockerHub(`cassiiopeia/suh-ai-flask`)에 push하고, 서버에서는 `docker compose pull && up -d`로 배포하는 방식으로 전환
- Ollama는 Windows 네이티브 유지, 컨테이너에서 `host.docker.internal:11434`로 접근 (실측 검증 완료)
- 설계 문서: `docs/superpowers/specs/2026-07-13-suh-ai-docker-deploy-design.md` (승인 완료)

⚙️ 작업 내용
---

- [ ] Ollama 주소 환경변수화: `config/app_config.py`에 `OLLAMA_API_URL` 추가, `service/ocr_service.py`·`service/vision_service.py` 생성자 기본값 변경
- [ ] `suh-ai-server/flask/Dockerfile` 신규 작성 (python:3.12-slim, Waitress 유지)
- [ ] `suh-ai-server/docker-compose.yml` 신규 작성 (restart: always, healthcheck, logs 볼륨)
- [ ] `SUH-AI-PROJECT-CONTROL.yaml` 워크플로우 교체: 빌드 → DockerHub push(latest + git-sha 태그) → SSH로 pull + up + `/health` 검증, `suh-ai-server/**` paths 필터 적용
- [ ] GitHub Secrets 등록: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (토큰 재발급 후 등록)
- [ ] 전환: 로컬 스모크 테스트 통과 후 NSSM `FlaskOCRService` 중지·삭제 → 컨테이너로 포트 5000 인계
- [ ] 롤백 경로 검증: 이전 git-sha 태그 재기동 / NSSM 재등록

⚠️ 선행 제약 (이슈 #46 충돌)
---

- #46 팰월드 관리 기능(`palworld_router` 등)은 Windows 서비스 제어(`Start-Service`/`Stop-Service`)와 호스트 파일 직접 접근(`C:\AI\palworld\`)을 사용하므로 **컨테이너 내부에서 동작 불가**
- 본 작업 실행 전 아래 중 하나를 반드시 결정해야 함:
  1. 팰월드 제어 로직을 호스트 네이티브 미니 서비스(palworld-agent)로 분리하고 컨테이너 Flask는 중계만 수행
  2. 팰월드 라우터를 컨테이너화 스코프에서 제외 (팰월드 기능만 네이티브 유지)
- 이 결정 없이 NSSM FlaskOCRService를 제거하면 팰월드 관리 기능이 전부 중단됨

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
