# 관제소 알림 허브 2단계 구현 계획: 프로젝트 이벤트 토큰 발급·교체·폐기

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리 화면에서 프로젝트 이벤트 토큰을 발급·교체·폐기한다. 서버 환경변수를 손으로 넣지 않아도 새 프로젝트를 붙일 수 있다.

**Architecture:** 토큰은 해시만 DB에 저장한다. 토큰 검증은 `project_event_tokens.is_project_token_valid` 한 함수로 모으고, 이벤트 입구와 attention push 입구가 모두 이 함수를 쓴다. 관리 화면에서 한 번이라도 발급한 프로젝트는 DB 토큰만 인정한다. 그 외 프로젝트는 기존 환경변수 경로를 그대로 쓴다.

**Tech Stack:** Python 3 / Flask / SQLite / pytest / 관리 화면 바닐라 JS

**Spec:** `docs/superpowers/specs/2026-11-13-control-tower-notification-hub-design.md` (5.3, 6장 2단계)

## Global Constraints

- 비밀값 원본: 환경변수 `CONTROL_TOWER_SECRET` 1개. 토큰 해시 키는 이 값에서 파생 (`HMAC-SHA256(key=SHA256("control-tower:event-token:" + secret), msg=token)` hex). 값이 없으면 발급·교체 불가(409 `secret_not_configured`), DB 관리 프로젝트 검증은 거부 + 경고 로그, 환경변수 토큰 경로와 Discord 발송은 그대로
- 토큰 값: `secrets.token_urlsafe(32)`, 응답으로 **발급 직후 1번만** 반환. DB·로그·감사 기록에 원문 금지
- 교체: 기존 현재 토큰 > 이전 토큰(만료 = 교체 시각 + 7일), 새 토큰 = 현재. 이전 토큰은 만료 전까지 유효
- DB 관리 전환: 프로젝트에 한 번이라도 발급하면 그 프로젝트는 DB 토큰(현재·만료 전 이전)만 인정. 폐기 후에도 DB 관리 유지 (환경변수로 되돌아가지 않음)
- 비교는 상수 시간 (`hmac.compare_digest`), 후보 전부 비교
- 감사: `CONTROL_EVENT_TOKEN_ISSUE`, `CONTROL_EVENT_TOKEN_REVOKE` (토큰 값 없이 project_id만)
- 1단계와 같은 코드 규칙 (한국어 짧은 주석, 영어 로그 접두사 `[control-tower event-token]`, 약어 금지, boolean is/has, 새 파일 300줄 미만, 단일 원본)
- 커밋 메시지 접두: `관제소 알림 허브: 프로젝트별 알림 종류, 토큰 발급, 받을 곳 등록, 언어별 클라이언트 : feat : {설명} https://github.com/Cassiiopeia/suh-project-control/issues/192`

## Review Focus

1. `CONTROL_TOWER_SECRET`이 없는 서버(지금 운영 상태) > 기존 elum 이벤트·attention push가 환경변수 토큰으로 계속 통과 (Task 1)
2. 교체 직후 이전 토큰으로 보낸 요청 > 통과, 7일 지난 뒤 > 401 (Task 1)
3. 폐기 후 환경변수 토큰으로 보낸 요청 > 401 (DB 관리 유지) (Task 1)
4. 발급 응답 외 어디에도 토큰 원문이 남지 않음 (DB, 로그, 감사, manage 응답) (Task 1, 2)
5. 토큰 발급 버튼 연타 > 마지막 토큰만 현재, 그 직전 것이 이전 (Task 2)

---

### Task 1: 토큰 저장소·해시·검증 + 두 입구 연결

**Files:**
- Modify: `config/control_tower_config.py` (`CONTROL_TOWER_SECRET_ENV = "CONTROL_TOWER_SECRET"`, `PREVIOUS_EVENT_TOKEN_VALID_DAYS = 7`)
- Modify: `service/control_tower/store_schema.py` (테이블 2개)
- Create: `service/control_tower/project_token_store.py` (`ProjectTokenStoreMixin`)
- Modify: `service/control_tower/store.py` (믹스인 연결, 300줄 넘으면 믹스인 목록 줄바꿈 등으로 맞춤)
- Create: `service/control_tower/project_event_tokens.py`
- Modify: `router/control_tower_router.py`, `router/control_tower_app_attention_intake.py` (검증 함수 교체)
- Modify: `service/control_tower/app_attention_view.py` (push 토큰 설정 여부를 공용 함수로)
- Test: `test/test_control_tower_project_event_tokens.py`

**Interfaces:**
- Produces:
  - 테이블 `project_event_token(project_id TEXT, slot TEXT, token_hash TEXT NOT NULL, created_at TEXT NOT NULL, expires_at TEXT, PRIMARY KEY(project_id, slot))` (slot: `current` | `previous`)
  - 테이블 `project_event_token_policy(project_id TEXT PRIMARY KEY, managed_since TEXT NOT NULL)` (행 있음 = DB 관리)
  - `ProjectTokenStoreMixin`: `rotate_project_token(project_id, token_hash, now, previous_expires_at) -> None` (한 트랜잭션: 현재 > 이전, 새 현재, 정책 행 보장), `delete_project_tokens(project_id) -> bool` (토큰 행만 삭제, 정책 유지), `load_project_token_state(project_id) -> ProjectTokenState`
  - `ProjectTokenState(is_db_managed: bool, current_created_at: datetime | None, previous_expires_at: datetime | None, token_hashes: tuple[tuple[str, datetime | None], ...])` (hash, expires_at)
  - `project_event_tokens.TokenSecretNotConfiguredError`
  - `issue_project_token(store, project_id: str, now: datetime, environ=os.environ) -> str` (원문 반환, 비밀값 없으면 예외)
  - `revoke_project_tokens(store, project_id: str) -> bool`
  - `is_project_token_valid(store, project_id: str, presented: str, now: datetime, environ=os.environ) -> bool`
  - `describe_project_token(store, project_id: str, now: datetime, environ=os.environ) -> dict` = `{is_db_managed, has_current, current_created_at, has_previous, previous_expires_at, is_env_configured}` (시각은 ISO, 만료된 이전은 has_previous False)
  - `is_token_secret_configured(environ=os.environ) -> bool`

- [ ] **Step 1: 실패 테스트** (임시 DB `ControlTowerStore`, environ dict 주입)
  - `test_env_fallback_when_not_db_managed`: 비밀값 없음 + env `CONTROL_EVENT_TOKEN_ELUM=abc` > `"abc"` 통과, `"x"` 거부
  - `test_issue_returns_token_and_stores_only_hash`: 발급 > 원문이 DB 어느 행에도 없음(전체 행 문자열 검사), 그 토큰 통과
  - `test_db_managed_ignores_env_token`: 발급 후 env 토큰 거부
  - `test_rotate_keeps_previous_until_expiry`: 발급 A > 교체 B > A·B 통과, now+7일+1초에 A 거부·B 통과
  - `test_revoke_rejects_everything_and_stays_db_managed`: 폐기 후 B 거부, env 토큰도 거부, `describe` is_db_managed True
  - `test_issue_without_secret_raises`, `test_db_managed_without_secret_rejects_with_warning` (caplog 1줄)
  - `test_empty_presented_rejected`
  - 라우터 2곳: 기존 `test_control_tower_events.py`·attention intake 테스트가 그대로 통과 (env 경로)

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_project_event_tokens.py -q`
- [ ] **Step 3: 구현** — 기존 `app_attention_tokens.is_presented_token_valid`는 env 경로로 재사용. 라우터는 `is_project_token_valid(runtime.store, project_id, presented, now)` 호출.
- [ ] **Step 4: 통과 확인** — 같은 명령 + 전체 테스트
- [ ] **Step 5: 커밋**

### Task 2: 관리 API·화면 (발급·교체·폐기, 상태 표시)

**Files:**
- Create: `router/control_tower_event_token_api.py` (`register_event_token_api`)
- Modify: `router/control_tower_router.py` (등록 1줄)
- Modify: `service/audit_service.py`, `static/js/audit.js` (감사 액션 2개, 라벨)
- Modify: `service/control_tower/manage_view.py` (프로젝트마다 `event_token` = `describe_project_token(...)`, 최상위 `is_token_secret_configured`)
- Create: `static/js/control-manage-event-token.js`, Modify: 관리 화면 템플릿·`control-manage.js` 연결 (1단계 `control-manage-event-kinds.js`와 같은 방식)
- Modify: `docs/control-tower/events/README.md` (토큰 받는 법: 관리 화면 발급, 교체 절차, 환경변수 방식은 기존 프로젝트 호환용)
- Test: `test/test_control_tower_event_token_api.py`

**Interfaces:**
- Consumes: Task 1 함수
- Produces:
  - `POST /control/projects/<project_id>/event-token` > `201 {"token": "<원문>", "previous_expires_at": <ISO|null>}` (교체면 이전 만료 시각); 없는 프로젝트 404 `unknown_project`; 비밀값 없음 409 `secret_not_configured`; 런타임 없음 503
  - `DELETE /control/projects/<project_id>/event-token` > 204 (토큰 없으면 404 `no_token`)
  - 화면: 프로젝트 영역에 "이벤트 토큰" — 상태(관리 방식: 환경변수/관리 화면, 현재 발급 시각, 이전 토큰 만료 시각), 버튼 발급(처음)·교체·폐기(확인 창). 발급 직후 토큰을 복사 가능한 상자에 1번만 표시 + "지금만 볼 수 있음" 안내. 비밀값 미설정이면 버튼 비활성 + 안내 문구.

- [ ] **Step 1: 실패 테스트** — 201 응답 토큰이 검증 통과 / manage 응답·감사 상세·로그(caplog)에 토큰 원문 없음 / 연속 2회 발급 > 두 번째가 현재, 첫 번째가 이전 / 폐기 204 > 이후 404 / 비밀값 없음 409 / 사용자 추가 프로젝트에도 발급
- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_event_token_api.py -q`
- [ ] **Step 3: 구현** — 프로젝트 존재 확인은 1단계와 같이 `load_manage_context(runtime).is_known_project`
- [ ] **Step 4: 통과 확인** — 같은 명령 + 전체 테스트, `node --check` 새 JS
- [ ] **Step 5: 커밋**

### 배포 후 확인 (사용자 요청 시)

- 서버 `.env`에 `CONTROL_TOWER_SECRET` 추가(32자 이상 임의 값) 후 서비스 재시작 > 관리 화면에서 토큰 발급 버튼 활성 확인
- 기존 elum 연동은 발급 전까지 환경변수 토큰으로 계속 동작 확인
