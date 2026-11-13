# 관제소 알림 허브 1단계 구현 계획: 프로젝트별 알림 종류 + Claude 코드 알림 + 이벤트 규격

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리 화면에서 프로젝트마다 알림 종류를 추가하면 그 프로젝트에만 Discord 채널이 생기고, `/control/events`와 내부 함수가 그 종류를 받아 보낸다. 첫 사례로 Claude 로그인 코드 발급·열람 알림을 붙인다.

**Architecture:** 사용자 정의 종류는 DB(`project_event_kind`)에 두고, 기존 덮어쓰기 병합(`registry_overrides.merge_overrides`)에서 `ProjectSpec.event_kinds`로 합친다. 동기화 계획·이벤트 검증·발송은 모두 실효 Registry의 `event_kinds`만 본다(출처 한 곳). 이 레포 안 발송은 HTTP 없이 `send_project_event` 내부 함수가 같은 `EventDispatcher` 경로를 탄다.

**Tech Stack:** Python 3 / Flask / SQLite (기존 `ControlTowerStore` 믹스인) / pytest / 관리 화면 바닐라 JS

**Spec:** `docs/superpowers/specs/2026-11-13-control-tower-notification-hub-design.md` (5.2, 5.6, 6장 1단계)

## Global Constraints

- 작업 위치: `suh-ai-server/flask`. 테스트: `python3 -m pytest test/ -q` (로컬 Mac은 `psutil`·`jsonschema` 없어 5개 수집 실패, 무관)
- 사용자 정의 kind 형식: `^[a-z][a-z0-9-]{1,31}$`
- 예약 kind (등록 불가): 프로젝트 채널 종류 5개 `status`·`error`·`report`·`deploy`·`attention`, 전역 `notice`·`alert`·`digest`, 이벤트 `info`, `_category`, `role:`로 시작
- `visible_to`: `dev`·`member` 조합, 빈 목록 = 관리자만 (`admin`은 항상 포함이라 저장 안 함), 기본 `("dev",)`
- 채널 이름(`channel_name`): 1~40자, 기본 = kind
- 이벤트 `fields`: 선택, `[{"name": str, "value": str}]` 최대 10개, name 1~40자, value 1~200자
- Claude 코드 알림에 **6자리 코드와 Gmail 주소 절대 포함 금지**
- 프로젝트 공통 규칙: 한국어 단계 주석, 로그 영어 + 고정 접두사(`[control-tower event-kind]` 등), 300줄 넘는 파일 새로 만들지 않기, boolean `is/has` 접두사
- 커밋: `/pro-commit` 템플릿 `관제소 알림 허브: 프로젝트별 알림 종류, 토큰 발급, 받을 곳 등록, 언어별 클라이언트 : feat : {설명} https://github.com/Cassiiopeia/suh-project-control/issues/192`, 건드린 경로만 스테이징

## Review Focus

1. 등록 안 된 kind로 보낸 이벤트 > 조용히 사라지지 않고 400 `unknown_kind` + 경고 로그 (Task 3)
2. 종류 삭제 후 > 그 채널은 지우지 않고 보관(이름 접두사 + 관리자만), 같은 kind 재등록 시 기존 채널 재사용 (Task 2)
3. 사용자 정의 종류 채널 이름이 기본 채널 이름(`신고` 등)과 같을 때 > 기본 채널을 가로채지 않음 (Task 2)
4. 관제소 런타임 미설정·Discord 미설정 상태에서 Claude 코드 발급 > 알림만 생략, 코드 발급 흐름은 그대로 (Task 5)
5. `fields` 값에 Discord 임베드 한도 초과 문자열 > 잘려서 발송, 400 아님은 검증 범위(200자) 안에서만 (Task 3)

---

### Task 1: 사용자 정의 종류 모델·저장소·병합·검증

**Files:**
- Modify: `service/control_tower/registry_models.py` (모델 추가, `ProjectSpec` 필드 추가)
- Modify: `service/control_tower/store_schema.py` (테이블 추가)
- Create: `service/control_tower/event_kind_store.py` (`EventKindStoreMixin`)
- Modify: `service/control_tower/store.py` (믹스인 연결)
- Modify: `service/control_tower/override_models.py` (`RegistryOverrides.project_event_kinds`)
- Modify: `service/control_tower/override_store.py` (`load_registry_overrides`에서 함께 읽기)
- Modify: `service/control_tower/registry_overrides.py` (`_merge_projects`에서 `event_kinds` 채우기)
- Create: `service/control_tower/event_kind_validation.py`
- Test: `test/test_control_tower_event_kinds.py`

**Interfaces:**
- Produces:
  - `registry_models.EventKindSpec(kind: str, channel_name: str, visible_to: tuple[str, ...] = ("dev",))` frozen dataclass
  - `registry_models.RESERVED_EVENT_KINDS: frozenset[str]` (Global Constraints 예약 목록, `role:` 접두는 검증 함수가 별도 확인)
  - `ProjectSpec.event_kinds: tuple[EventKindSpec, ...] = ()`
  - 테이블 `project_event_kind(project_id TEXT, kind TEXT, channel_name TEXT NOT NULL, visible_to TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(project_id, kind))` (`visible_to` = 쉼표 구분)
  - `EventKindStoreMixin.list_project_event_kinds() -> dict[str, tuple[EventKindSpec, ...]]` (생성 순)
  - `EventKindStoreMixin.insert_project_event_kind(project_id: str, spec: EventKindSpec, now: datetime) -> bool` (이미 있으면 False)
  - `EventKindStoreMixin.delete_project_event_kind(project_id: str, kind: str) -> bool`
  - `RegistryOverrides.project_event_kinds: dict[str, tuple[EventKindSpec, ...]]` (기본 빈 dict, `EMPTY_OVERRIDES` 갱신)
  - `event_kind_validation.parse_new_event_kind(payload: dict) -> tuple[EventKindSpec | None, list[str]]` (잘못된 필드 이름 목록: `kind`·`channel_name`·`visible_to`)

- [ ] **Step 1: 실패 테스트 작성** (`test/test_control_tower_event_kinds.py`)
  - `test_parse_new_event_kind_defaults`: `{"kind": "claude-code"}` > `EventKindSpec("claude-code", "claude-code", ("dev",))`, 오류 `[]`
  - `test_parse_new_event_kind_rejects_reserved`: `report`, `alert`, `info`, `_category`, `role:dev` 각각 > 오류 `["kind"]`
  - `test_parse_new_event_kind_rejects_bad_format`: `Claude`, `a`, `x` * 33, `1abc` > `["kind"]`
  - `test_parse_new_event_kind_visible_to`: `["member","dev"]`·`[]`(관리자만) 허용, `["admin"]`·`["everyone"]`·`"dev"`(리스트 아님) > `["visible_to"]`
  - `test_parse_new_event_kind_channel_name_length`: 41자 > `["channel_name"]`
  - `test_store_insert_list_delete`: 임시 DB `ControlTowerStore` > insert 2개 > list 순서·값 > 같은 kind 재insert False > delete True > list에서 빠짐
  - `test_merge_overrides_attaches_event_kinds`: `RegistryOverrides(project_event_kinds={"elum": (spec,)})` > 병합 결과 elum `event_kinds == (spec,)`, 다른 프로젝트 `()`; 사용자 추가 프로젝트에도 붙음

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_event_kinds.py -q` > ImportError/FAIL

- [ ] **Step 3: 구현** — 위 Interfaces 그대로. 저장소 믹스인은 `override_store.py`의 시각 변환 헬퍼 패턴을 따른다. 병합은 `_merge_projects`의 `replace(...)`에 `event_kinds=overrides.project_event_kinds.get(project.id, ())` 추가.

- [ ] **Step 4: 통과 확인** — 같은 명령 PASS, 이어서 `python3 -m pytest test/ -q -k control_tower` 기존 테스트 깨짐 없음

- [ ] **Step 5: 커밋**

### Task 2: Discord 동기화가 사용자 정의 종류 채널을 계획

**Files:**
- Modify: `service/control_tower/discord_sync_plan.py`
- Test: `test/test_control_tower_discord_sync.py` (기존 파일에 추가, 기존 fakes 사용)

**Interfaces:**
- Consumes: `ProjectSpec.event_kinds`, `EventKindSpec` (Task 1)
- Produces: 바인딩 키 `(project_id, kind)` = 사용자 정의 채널 id (발송이 이 키로 채널 찾음)

- [ ] **Step 1: 실패 테스트**
  - `test_plan_admin_only_custom_kind`: `visible_to=()` > 관리자 역할만 보기 허용
  - `test_plan_creates_custom_event_kind_channel`: elum에 `EventKindSpec("claude-code", "클로드코드", ("dev",))` > `ACTION_CREATE_CHANNEL`, scope `elum`, kind `claude-code`, 이름 `클로드코드`, parent_scope `elum`, 공개 = elum-dev + 관리자 (기존 `error` 채널과 같은 overwrite 모양)
  - `test_plan_custom_kind_does_not_take_default_channel_by_name`: 사용자 정의 `channel_name="신고"`이고 elum 카테고리에 `report`로 바인딩된 `신고` 채널이 있을 때 > 그 채널을 바인딩하지 않고 새 채널 생성
  - `test_plan_archives_removed_custom_kind_channel`: 바인딩 `("elum","old-kind")`가 있고 현재 `event_kinds`에 없음 > `ACTION_ARCHIVE_CHANNEL` (보관 이름 + 관리자만), 기본 5종 바인딩은 보관 대상 아님
  - `test_plan_reuses_bound_channel_when_kind_readded`: 바인딩된 채널이 보관 이름이어도 kind가 다시 등록되면 `ACTION_UPDATE_CHANNEL`로 원래 이름·권한 복원

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_discord_sync.py -q`

- [ ] **Step 3: 구현**
  - `plan()`의 프로젝트 채널 루프 뒤에 `project.event_kinds` 루프: `_plan_channel(project.id, spec.kind, spec.visible_to, parent_scope=project.id, name=spec.channel_name)`
  - `_plan_channel`에 키워드 `name: str | None = None` 추가 (없으면 기존 `channel_names` 조회)
  - 보관: 등록 프로젝트 scope의 바인딩 중 kind가 기본 5종·`_category`·`role:*`가 아니고 현재 `event_kinds`에도 없는 것 > `ACTION_ARCHIVE_CHANNEL` (기존 `_archived_name`·`_managed_overwrites(channel, scope, ())` 재사용). `_collect_live_bound_channel_ids`가 이 채널을 claimed로 잡지 않게 같은 조건 적용.

- [ ] **Step 4: 통과 확인** — 같은 명령 + `-k discord` 전체 PASS

- [ ] **Step 5: 커밋**

### Task 3: 이벤트 입구·발송이 사용자 정의 종류와 fields를 받음

**Files:**
- Modify: `service/control_tower/alert_planner.py` (`Notification.fields`)
- Modify: `service/control_tower/discord_messages.py` (`to_embed` fields)
- Modify: `service/control_tower/event_dispatcher.py`
- Test: `test/test_control_tower_events.py`, `test/test_control_tower_discord_messages.py`

**Interfaces:**
- Consumes: 실효 Registry의 `ProjectSpec.event_kinds` (Task 1)
- Produces:
  - `Notification.fields: tuple[tuple[str, str], ...] = ()` (기존 생성 코드 수정 불필요)
  - `validate_event_payload(payload: dict, allowed_kinds: frozenset[str]) -> list[str]` (필드 순서: kind, severity, title, body, fields, dedupe_key, url)
  - `EventDispatcher.allowed_event_kinds(project_id: str) -> frozenset[str]` = `EVENT_KINDS` ∪ 그 프로젝트 `event_kinds`의 kind
  - `accept_event` 응답: 모르는 kind > `400 {"error": "unknown_kind", "kind": <받은 값 50자 정리>}` + `logger.warning("[control-tower event] unknown kind : project %s kind %s")`; 그 외 기존과 같음
  - 채널 찾기: 사용자 정의 kind는 `(project_id, kind)` 바인딩, 없으면 기존처럼 `#관제-긴급` 대체

- [ ] **Step 1: 실패 테스트**
  - `test_event_with_custom_kind_is_delivered_to_its_channel`: registry elum `event_kinds=(EventKindSpec("claude-code","claude-code"),)`, 바인딩 `("elum","claude-code")="c-1"` > 202, 발송 채널 `c-1`
  - `test_event_with_unregistered_kind_returns_unknown_kind`: `kind="feedback"` > 400 `{"error":"unknown_kind","kind":"feedback"}`, 경고 로그 1줄, 저장(record_event) 없음
  - `test_event_fields_validation`: 11개 > `["fields"]`; name 41자 > `["fields"]`; value 201자 > `["fields"]`; 리스트 아님 > `["fields"]`
  - `test_event_fields_reach_embed`: fields 2개 > 임베드 `fields == [{"name":..,"value":..,"inline": True}, ...]`
  - `test_to_embed_appends_downtime_after_fields` (discord_messages): 복구 알림 + fields > fields 뒤에 다운 시간 field
  - 기존 `VALID_PAYLOAD`(`report`) 테스트 그대로 통과

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_events.py test/test_control_tower_discord_messages.py -q`

- [ ] **Step 3: 구현** — 이벤트 `fields` 상수 3개(`EVENT_FIELDS_MAX_COUNT = 10`, `EVENT_FIELD_NAME_MAX_LENGTH = 40`, `EVENT_FIELD_VALUE_MAX_LENGTH = 200`)를 `event_dispatcher.py`에 둔다. `accept_event`는 검증 전에 `allowed_event_kinds`로 kind만 먼저 판정해 `unknown_kind`를 분리한다.

- [ ] **Step 4: 통과 확인** — 같은 명령 + `-k control_tower` 전체 PASS

- [ ] **Step 5: 커밋**

### Task 4: 관리 API·화면에서 종류 추가·삭제 > 즉시 동기화

**Files:**
- Create: `router/control_tower_event_kind_api.py` (`register_event_kind_api`)
- Modify: `router/control_tower_router.py` (등록 1줄, 주석 `# 프로젝트 알림 종류 API (nginx 키 검사 대상)`)
- Modify: `service/audit_service.py` (`CONTROL_EVENT_KIND_CREATE`, `CONTROL_EVENT_KIND_DELETE`)
- Modify: `service/control_tower/manage_view.py` (`build_manage` 프로젝트 항목에 `event_kinds` 목록)
- Modify: 관리 화면 JS (`static/js/control-manage-actions.js` 및 해당 템플릿) — 프로젝트 관리 영역에 "알림 종류" 목록·추가·삭제
- Test: `test/test_control_tower_event_kind_api.py`

**Interfaces:**
- Consumes: Task 1 저장소·검증, `discord_sync.sync_discord`, `DISCORD_SYNC_LOCK`
- Produces:
  - `POST /control/projects/<project_id>/event-kinds` body `{kind, channel_name?, visible_to?}` > `201 {"kind":..., "channel_name":..., "visible_to":[...]}`; 잘못된 값 `400 {"error":"invalid","fields":[...]}`; 없는 프로젝트 `404 unknown_project`; 이미 있음 `409 duplicate_kind`
  - `DELETE /control/projects/<project_id>/event-kinds/<kind>` > `204`, 없으면 `404 unknown_kind`
  - 둘 다 런타임 없으면 503, 성공 후 백그라운드 스레드로 동기화 1회 (`DISCORD_SYNC_LOCK` 잡고, Discord 미설정이면 생략) — 응답은 동기화를 기다리지 않음
  - `GET /control/manage` 응답의 각 프로젝트에 `event_kinds: [{kind, channel_name, visible_to}]`

- [ ] **Step 1: 실패 테스트** (`control_tower_admin_fixtures` 패턴의 Flask 테스트 앱)
  - 생성 201 + 저장소 반영 + 감사 액션 `CONTROL_EVENT_KIND_CREATE`
  - 예약 kind 400 `fields == ["kind"]`, 없는 프로젝트 404, 중복 409
  - 삭제 204 / 없는 kind 404 + 감사 `CONTROL_EVENT_KIND_DELETE`
  - 성공 시 동기화 함수가 1회 호출됨 (테스트에서 동기 실행으로 바꿔치기), 실패 응답에서는 호출 안 됨
  - `/control/manage`에 `event_kinds` 포함

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_event_kind_api.py -q`

- [ ] **Step 3: 구현** — 동기화는 저장 후 `apply_overrides`로 실효 Registry를 다시 만들어 `sync_discord`에 넘긴다 (`control_tower_admin_api.py`의 동기화 버튼 경로와 같은 순서). 화면: 프로젝트 행 펼침 안에 표(종류·채널 이름·공개 대상·삭제)와 추가 폼, 기존 디자인 토큰·공통 컴포넌트만 사용.

- [ ] **Step 4: 통과 확인** — 같은 명령 + 전체 `python3 -m pytest test/ -q`

- [ ] **Step 5: 커밋**

### Task 5: 내부 발송 함수 + Claude 로그인 코드 발급·열람 알림

**Files:**
- Create: `service/control_tower/project_event_sender.py`
- Modify: `service/claude_login_code_service.py` (`_finish` 성공 시)
- Modify: `router/claude_login_router.py` (`code_status` 열람 기록 시)
- Modify: `config/claude_login_config.py` (상수 2개)
- Test: `test/test_control_tower_project_event_sender.py`, `test/test_claude_login_code_service.py`, `test/test_claude_login_router.py`

**Interfaces:**
- Consumes: `runtime.get_runtime()`, `EventDispatcher.accept_event` (Task 3)
- Produces:
  - `send_project_event(project_id: str, kind: str, title: str, *, fields: list[tuple[str, str]] = (), body: str = "", severity: str = "info", url: str | None = None, dedupe_key: str | None = None) -> bool` — 런타임 없음·검증 실패·발송 실패·예외 모두 False + 경고 로그(`[control-tower project event]`), **예외를 던지지 않음**
  - `claude_login_config.CONTROL_TOWER_PROJECT_ID = "suh-ai"`, `CONTROL_TOWER_EVENT_KIND = "claude-code"`
  - 발급 알림: 제목 `Claude 코드 발급`, fields `[("계정", display_name), ("IP", client_ip), ("브라우저", user_agent 앞 60자)]`, dedupe `claude-code:issued:{job_id}`
  - 열람 알림: 제목 `Claude 코드 열람`, fields 같은 구성, dedupe `claude-code:view:{job_id}:{client_ip}`

- [ ] **Step 1: 실패 테스트**
  - sender: 런타임 None > False, 예외 없음 / 가짜 dispatcher가 202 > True / 400 > False + 경고 로그 / dispatcher 예외 > False
  - code service: 성공 `_finish` > `send_project_event` 1회, 인자에 코드 6자리·gmail 주소가 **어디에도 없음**(문자열 검사), 실패 `_finish` > 호출 없음
  - router: 첫 열람 > 1회, 같은 job·IP 재조회 > 추가 호출 없음 (기존 `should_record_view`와 같은 조건)

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_project_event_sender.py test/test_claude_login_code_service.py test/test_claude_login_router.py -q`

- [ ] **Step 3: 구현** — `send_project_event`는 `accept_event(project_id, payload, now)`를 그대로 호출(검증·중복 억제·발송 공통 경로). 코드 서비스·라우터는 감사 기록 바로 뒤에 호출.

- [ ] **Step 4: 통과 확인** — 같은 명령 + 전체 테스트 PASS

- [ ] **Step 5: 커밋**

### Task 6: 이벤트 연동 규격 문서 + 스키마 계약 테스트

**Files:**
- Create: `docs/control-tower/events/README.md`
- Create: `docs/control-tower/events/events-v1.schema.json` (JSON Schema 2020-12)
- Create: `docs/control-tower/events/examples/valid_basic.json`, `valid_custom_kind_fields.json`, `invalid_fields_too_many.json`, `invalid_title_empty.json`
- Test: `test/test_control_tower_events_contract.py`

**Interfaces:**
- Consumes: `validate_event_payload` (Task 3)

- [ ] **Step 1: 실패 테스트** — examples 폴더의 `valid_*`는 `validate_event_payload(payload, allowed_kinds)`가 `[]`, `invalid_*`는 비어 있지 않음 (`allowed_kinds`는 기본 5종 + `claude-code`). `jsonschema`가 설치된 환경이면 스키마 검증 결과도 같은지 확인, 없으면 그 부분만 skip (attention 계약 테스트와 같은 방식).

- [ ] **Step 2: 실패 확인** — `python3 -m pytest test/test_control_tower_events_contract.py -q`

- [ ] **Step 3: 문서 작성** — attention README 구성을 따른다: 흐름도, 주소 `POST https://ai.suhsaechan.kr/api/flask/control/events`, 헤더 `X-Control-Token`, 필드 표, 응답 코드 표(202·400 invalid·400 unknown_kind·401·404 unknown_project·503), 알림 종류 추가 방법(관리 화면), curl·Python·Java 예시, "모바일 앱에서 직접 보내지 말 것", "개인정보는 보내는 쪽 판단, 가급적 제외", 쌓인 개수 알림은 attention 사용 안내.

- [ ] **Step 4: 통과 확인** — 같은 명령 PASS

- [ ] **Step 5: 커밋**

### 배포 후 확인 (구현 완료 뒤, 사용자 요청 시)

- 관리 화면 > suh-ai 프로젝트에 종류 `claude-code` (공개 대상 비움 = 관리자만) 추가 > Discord `SUH AI 서버` 카테고리에 채널 생성 확인
- Claude 로그인 코드 받기 > 채널에 발급·열람 알림, 코드·Gmail 주소 없음 확인
