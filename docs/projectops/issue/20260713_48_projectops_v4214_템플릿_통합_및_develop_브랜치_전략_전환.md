📝 현재 문제점
---

- 기존 suh-template 통합본(v2.7.7)이 오래되어 최신 projectops 템플릿(v4.2.14)과 큰 격차 발생 (BREAKING CHANGES CRITICAL 4건 · WARNING 3건)
- 브랜치 전략이 구버전 deploy 방식 그대로라 신규 릴리스 파이프라인(develop→main PR automerge)을 사용할 수 없음
- 레거시 워크플로우(AUTO-CHANGELOG-CONTROL, SUH-ISSUE-HELPER-API/MODULE)가 신형과 공존 시 이슈 댓글 중복·릴리스 PR 이중 처리 위험
- python 프로젝트(suh-ai-server/flask)에 버전 동기화 대상 파일(pyproject.toml)이 없어 버전 관리가 version.yml 단독으로만 동작

🛠️ 해결 방안 / 제안 기능
---

- npx projectops 통합 마법사로 템플릿 v4.2.14 전체 설치 (버전관리 + 자동화 워크플로우 + 이슈·PR 템플릿)
- develop(개발) / main(배포) 브랜치 전략으로 전환 — 마법사 입력 오타로 생성된 devlop 브랜치를 develop으로 정정
- Docker 기반 CI/CD 워크플로우는 마이그레이션 전이므로 자동 트리거를 비활성화한 껍데기 상태로 유지 (추후 #47에서 구현)

⚙️ 작업 내용
---

- projectops v4.2.14 마법사 실행: 공통 워크플로우 9종 + python 워크플로우 3종 설치, 레거시 3종 .bak 무해화, docs/suh-template → docs/projectops 이동
- version.yml 갱신: project_types [python], project_paths suh-ai-server/flask, deploy_branch develop
- devlop 오타 브랜치 정정: 로컬/origin 브랜치 rename 및 워크플로우·version.yml 참조 4곳 수정
- Docker 계열 워크플로우 4종(PYTHON-CI, PYTHON-SIMPLE-CICD, PYTHON-PR-PREVIEW, SECRET-FILE-UPLOAD) 자동 트리거 주석 처리 — 기존 Windows 서버 배포(SUH-AI-PROJECT-CONTROL)와 이중 배포 방지, workflow_dispatch 수동 실행만 허용
- suh-ai-server/flask/pyproject.toml 신규 추가 — 버전 동기화(version_manager) 대상 확보
- SECRET-FILE-UPLOAD의 PROJECT_NAME 플레이스홀더를 suh-project-control로 정정

🙋‍♂️ 담당자
---

- 인프라: Cassiiopeia
