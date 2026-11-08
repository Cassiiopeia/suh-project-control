# 앱 확인할 일(app attention) 연동 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 앱들이 attention v1 규격으로 내보내는 "확인할 일"을 관제소가 수집(pull)·수신(push)해 저장하고, 대시보드·관리 화면·디스코드 `#확인할일` 채널·일일 요약으로 보여 준다.

**Architecture:** 규격 원본은 JSON Schema 파일. Flask 쪽은 순수 모듈(검증 > 규칙 평가 > 메시지)과 부수효과 모듈(HTTP 수집, 저장, 발송)을 나누고, pull과 push가 같은 `AppAttentionIngest.ingest` 하나를 지난다. 폴러 틱에 `AppAttentionStep` 하나를 붙인다.

**Tech Stack:** Python 3.11+, Flask, SQLite(WAL), requests, 기존 관제소 모듈, 바닐라 JS + 미리 빌드된 Tailwind/daisyUI.

**Spec:** `docs/superpowers/specs/2026-11-08-control-tower-attention-integration-design.md`

## Global Constraints

- 모든 경로는 `suh-ai-server/flask/` 기준 (별도 표기 제외). 테스트 실행: `cd suh-ai-server/flask && python3 -m pytest test/ -q`
- 새 의존성은 `requirements-dev.txt`의 `jsonschema` 하나만 (운영 의존성 추가 금지)
- 파일 300줄 이하. 300줄 근접 파일(`poller.py` 280, `store.py` 297, `control.js` 297, `control-manage.js` 296, `registry_loader.py` 286, `discord_sync_plan.py` 273)은 import·등록·호출 몇 줄만 추가
- 테스트 파일은 새로 `test/test_control_tower_app_attention_<영역>.py`, 한국어 문장 테스트 이름, 첫 줄 한국어 docstring
- 코드 주석·이름 규칙: 사용자 전역 코딩 규칙 (boolean `is/has/can/should`, 약어 금지, 한국어 짧은 주석, 로그는 영어 `[control-tower app-attention] ...`)
- 기능 이름 `app_attention` (기존 overview `needs_attention`과 구분). 화면 문구 "앱 확인할 일"
- 시각은 모두 timezone-aware UTC `datetime`, 저장은 ISO 문자열 (기존 store 관례)
- 토큰 값은 절대 로그·응답·DB에 남기지 않음. 화면에는 설정 여부만
- 관리 API 실패 형식: 400 `{"error":"invalid","fields":[...]}`, 런타임 없음 503 `{"error":"unavailable"}`. 상태 변경 라우트는 `@audited(AuditCategory.CONTROL_TOWER, AuditAction.<새 항목>)`
- 요청은 프론트에서 `window.apiFetch` 사용
- 상수 값(스펙에서 고정): 항목 최대 100, 본문 64KB(65536 bytes), 소스 timeout 기본 5초(1~10), interval 기본 60초(60~3600), 수집 시점 여유 5초, 틱당 수집 상한 10초, 병렬 8, `new` 쿨다운 10분, push 전용 소스 최소 5분 주기, 끊김 판정 `stale_after_seconds` 기본 interval×5, 빠진 항목 7일 후 삭제, 이력 90일, label 40자, group 20자, description 200자, detail 80자, unit 12자, key 64자, source_id `^[a-z][a-z0-9]*$` 20자

## Review Focus

1. 같은 항목의 count가 그대로인데 total이 늘었을 때(처리 1 + 신규 1) `new` 알림이 나가야 한다 → Task 3 테스트
2. 앱이 비정상 JSON·거대 응답·느린 응답을 줘도 틱이 10초 넘게 밀리지 않고 그 소스만 실패 기록 → Task 4·5 테스트
3. 관제소 재배포(DB 유지) 직후 첫 틱에 알림 폭주 없음, DB 새로 만든 뒤 첫 성공은 기준선 → Task 3·4 테스트
4. 소스 삭제 후 같은 id로 다시 등록하면 이전 이력·알림 상태가 남아 있지 않음 → Task 2 테스트
5. push와 pull이 동시에 같은 소스를 처리해도 `generated_at` 역순 스냅샷이 최신 값을 덮지 않음 → Task 4 테스트

---

### Task 1: 규격 원본과 검증기

**Files:**
- Create: `docs/control-tower/attention/attention-v1.schema.json` (레포 루트 기준), `docs/control-tower/attention/examples/valid_*.json` 4개 이상, `invalid_*.json` 8개 이상
- Create: `service/control_tower/app_attention_models.py`, `service/control_tower/app_attention_validation.py`
- Modify: `requirements-dev.txt` (`jsonschema==4.25.1` 추가)
- Test: `test/test_control_tower_app_attention_contract.py`

**Interfaces (Produces):**
- `app_attention_models.py`:
  - 상수 `ITEM_KINDS = ("count","gauge","state")`, `ITEM_LEVELS = ("ok","info","warning","critical")`, `ITEM_STATES = ("ok","degraded","down","unknown")`, `ENVIRONMENTS = ("production","staging","development")`, 위 Global Constraints 길이·개수 상수
  - `@dataclass(frozen=True) class AttentionItem`: key, label, kind, level, group, description, admin_url, latest_at(datetime|None), detail, count(int|None), total(int|None), value(float|None), limit(float|None), unit, state, raw(dict, 원본 항목)
  - `@dataclass(frozen=True) class AttentionSnapshot`: major_version(int), app, app_version, environment, admin_base_url, generated_at(datetime), poll_after_seconds(int|None), items(tuple[AttentionItem,...])
- `app_attention_validation.py`:
  - `@dataclass(frozen=True) class ValidationResult`: snapshot(AttentionSnapshot|None), errors(tuple[str,...]) 최상위 오류(있으면 snapshot None), dropped_items(tuple[tuple[str,str],...]) (key 또는 `#index`, 사유)
  - `def parse_attention_snapshot(document: object) -> ValidationResult`
  - 규칙: 스펙 3.4 그대로. 모르는 필드 무시. 주 버전 1만 허용(그 외 최상위 오류 `unsupported_version`). 항목 단위 위반은 그 항목만 버림. key 중복은 뒤의 것 버림. 상대 `admin_url`은 `admin_base_url`과 합침, 절대 URL은 https만. 모르는 kind는 `AttentionItem(kind=그 값)`으로 유지(count/value/state None)
  - 스키마는 미지 kind를 허용해야 한다(`kind`는 패턴 `^[a-z][a-z0-9_]*$`, count/gauge/state일 때만 kind별 필드 필수 — `if/then`).

- [ ] **Step 1: 스키마와 예시 작성** — 스펙 3.3~3.4의 모든 필드·제한. valid 예시: 스펙 3.3 본문, 빈 items, 미지 kind 포함, 상대 admin_url. invalid 예시: schema 값 틀림, version "2.0", generated_at 없음, items 101개(생성 스크립트 없이 손으로 101개 작성 대신 테스트 코드에서 생성 — invalid 예시 파일 목록에서는 제외 가능), key 대문자, label 41자, count 음수, gauge value 없음, state 값 틀림
- [ ] **Step 2: 실패하는 계약 테스트 작성**
  - `test_모든_예시에서_스키마와_검증기의_판정이_같다`: 각 예시 파일에 대해 `jsonschema.Draft202012Validator(schema).is_valid(doc)` == `(parse_attention_snapshot(doc).errors == () and not dropped_items)` (항목 단위 위반 예시는 스키마 invalid ↔ 검증기 dropped_items 비어 있지 않음으로 비교)
  - `test_모르는_필드는_무시하고_모르는_kind는_항목을_유지한다`
  - `test_상대_admin_url은_기준_주소와_합치고_http_절대주소는_버린다`
  - `test_항목_단위_위반은_그_항목만_버리고_사유를_남긴다`
  - `test_주_버전이_1이_아니면_최상위_오류다`
  - `test_항목이_100개를_넘으면_최상위_오류다`
- [ ] **Step 3: 구현**, **Step 4: 테스트 통과**, **Step 5: 커밋** (`/pro-commit` 규칙: 내가 만든 경로만 스테이징)

### Task 2: 저장소

**Files:**
- Modify: `service/control_tower/store_schema.py` (테이블 6개 DDL을 `SCHEMA_STATEMENTS`에 추가), `service/control_tower/store.py` (mixin 상속 추가 + `purge()`에서 `self.purge_app_attention(now)` 1줄)
- Create: `service/control_tower/app_attention_store.py`
- Test: `test/test_control_tower_app_attention_store.py`

**Interfaces (Produces):** 스펙 5.4 테이블 그대로. 모델은 `app_attention_store.py`에 frozen dataclass:
- `AttentionSource(project_id, source_id, url, is_enabled, mode, interval_seconds, timeout_seconds, stale_after_seconds, created_at, updated_at)` (`mode` ∈ `pull`/`push`/`both`)
- `AttentionSourceState(project_id, source_id, last_attempt_at, last_success_at, last_result, last_error, consecutive_failures, etag, last_generated_at, app, app_version, environment, is_baseline_done, failure_alerted_at)`
- `StoredAttentionItem(project_id, source_id, key, kind, label, level, group, description, admin_url, latest_at, detail, count, total, value, limit, unit, state, raw_json, first_seen_at, updated_at, missing_since)`
- `AttentionItemOverride(project_id, source_id, key, is_hidden, label, level_policy, alert_rule, threshold, channel_kind)` (모두 None = 기본)
- `AttentionItemAlertState(project_id, source_id, key, last_alerted_at, last_alerted_total, last_alerted_count, last_alerted_level, is_threshold_exceeded, pending_new_count)`
- Mixin `AppAttentionStoreMixin` 메서드:
  - `list_attention_sources() -> list[AttentionSource]`, `get_attention_source(project_id, source_id)`, `save_attention_source(source)`(upsert), `delete_attention_source(project_id, source_id) -> bool` (같은 키의 state·item·override·alert·history 모두 삭제, 한 트랜잭션)
  - `get_attention_source_state(...)`, `load_attention_items(project_id, source_id) -> dict[str, StoredAttentionItem]`, `load_all_attention_items() -> list[StoredAttentionItem]`, `load_attention_overrides(project_id, source_id) -> dict[str, AttentionItemOverride]`, `save_attention_override(override)`, `load_attention_alert_states(...) -> dict[str, AttentionItemAlertState]`
  - `commit_attention_result(project_id, source_id, state, items_to_upsert, missing_keys, alert_states, now, expected_last_generated_at) -> bool`: 한 `_write_transaction()` 안에서 현재 state의 `last_generated_at`이 `expected_last_generated_at`과 다르면 False(다른 경로가 먼저 반영, 호출자는 버림). 같으면 state 저장, 항목 upsert(값 바뀐 항목만 history 1행), missing_keys는 `missing_since` 설정(이미 있으면 유지), 다시 나타난 항목은 `missing_since` NULL, alert_states 저장
  - `record_attention_failure(project_id, source_id, state)` (항목은 건드리지 않음)
  - `purge_app_attention(now)`: history 90일, `missing_since` 7일 지난 항목 삭제
- [ ] 테스트 (각 1개 이상): upsert·조회 왕복, 삭제가 관련 테이블을 모두 비움(Review Focus 4), 값 안 바뀌면 history 안 쌓임, expected_last_generated_at 불일치면 False·변경 없음, missing 7일 정리, history 90일 정리
- [ ] 구현 > 통과 > 커밋

### Task 3: 규칙 평가와 메시지 (순수 함수)

**Files:**
- Create: `service/control_tower/app_attention_rules.py`, `service/control_tower/app_attention_messages.py`
- Test: `test/test_control_tower_app_attention_rules.py`

**Interfaces:**
- Consumes: Task 1 `AttentionItem`, Task 2 `StoredAttentionItem`, `AttentionItemOverride`, `AttentionItemAlertState`, `AttentionSourceState`
- Produces (`app_attention_rules.py`):
  - 상수 `ALERT_RULES = ("new","threshold","state","level","off")`, `LEVEL_POLICIES = ("app","info","warning","critical","ok")`, `DEFAULT_RULE_BY_KIND = {"count":"new","gauge":"threshold","state":"state"}` (그 외 `level`), `NEW_ALERT_COOLDOWN = timedelta(minutes=10)`, `DEFAULT_CHANNEL_KIND = "attention"`
  - `@dataclass(frozen=True) class EffectiveItem`: item(AttentionItem), label, level, rule, threshold(float|None), channel_kind, is_hidden
  - `def resolve_effective_item(item, override: AttentionItemOverride | None) -> EffectiveItem`
  - `@dataclass(frozen=True) class AlertLine`: key, label, level, admin_url, text(한 줄 설명, 예 "새 의견 +5, 지금 8건"), channel_kind, is_recovery
  - `def evaluate_item_alerts(effective_items: list[EffectiveItem], previous_items: dict[str, StoredAttentionItem], alert_states: dict[str, AttentionItemAlertState], is_baseline: bool, is_production: bool, now) -> tuple[list[AlertLine], dict[str, AttentionItemAlertState]]`
    - 기준선이거나 비production: 알림 없음, alert_state는 현재 값으로 맞춤(다음 비교 기준)
    - `new`: 증가분 = total 둘 다 있으면 total 차이, 아니면 count 차이(음수면 0). 쿨다운 안이면 `pending_new_count`에 누적만, 쿨다운 지나면 누적+이번 증가분으로 1줄
    - `threshold`: 기준(threshold > item.limit) 없으면 알림 없음. 미초과→초과 1줄, 초과→미초과 해소 1줄(`is_recovery`)
    - `state`: ok→비ok 1줄, 비ok→ok 해소 1줄, 비ok끼리 바뀌어도 1줄
    - `level`: 유효 수준 순서(ok<info<warning<critical) 상승 시 1줄
    - `off`, `is_hidden`, 유효 수준 `ok`: 줄 없음(상태는 갱신)
  - `def evaluate_source_health(source, state: AttentionSourceState, is_project_down: bool, now) -> Literal["disconnected","recovered"] | None`: 마지막 성공(없으면 등록 시각)으로부터 `stale_after_seconds` 넘고 `failure_alerted_at` 없음 > disconnected (단 is_project_down이면 None). 성공 직후 `failure_alerted_at` 있음 > recovered
- Produces (`app_attention_messages.py`):
  - `def build_item_notifications(project_id, project_name, source_id, lines: list[AlertLine], dedupe_suffix: str) -> list[Notification]`: 채널 kind별로 묶어 1건씩, critical 줄이 하나라도 있으면 추가로 `scope="global", kind="alert"` 1건. 제목 `"{project_name} 확인할 일"`, 본문 줄 `"• [label](admin_url) text"`(url 없으면 링크 없이), link_url = 첫 줄 admin_url. severity = 묶음 최고 수준(info→`info`, warning→`warning`, critical→`critical`). dedupe_key `f"attention:{project_id}:{source_id}:{dedupe_suffix}"`
  - `def build_source_health_notification(project_id, project_name, source_id, verdict, reason) -> Notification` (kind `error`)
- [ ] 테스트: Review Focus 1, 쿨다운 합산(+3 후 5분 뒤 +2 → 알림 없음, 11분 뒤 +1 → "+6"), threshold 왕복, state 3경우, level 상승만, 기준선·비production 무알림, hidden/off 무알림, critical이면 global alert 추가, 연동 끊김 1번·복구 1번·프로젝트 down이면 생략
- [ ] 구현 > 통과 > 커밋

### Task 4: 수집과 단일 처리 경로

**Files:**
- Create: `service/control_tower/app_attention_tokens.py`, `service/control_tower/app_attention_fetch.py`, `service/control_tower/app_attention_ingest.py`
- Modify: `router/control_tower_router.py` (`_is_token_valid`가 `app_attention_tokens.is_presented_token_valid` 사용 → `_PREVIOUS` 지원)
- Test: `test/test_control_tower_app_attention_ingest.py`, `test/test_control_tower_app_attention_tokens.py`

**Interfaces:**
- `app_attention_tokens.py`: `PULL_TOKEN_ENV_PREFIX = "CONTROL_PULL_TOKEN_"`, `PREVIOUS_TOKEN_SUFFIX = "_PREVIOUS"`, `def to_env_id(identifier) -> str` (대문자, `-`→`_`), `def pull_token_env_name(project_id, source_id) -> str` (`PREFIX + P + "__" + S`), `def read_pull_token(project_id, source_id) -> str | None`(현재 값만, 보낼 때), `def is_pull_token_configured(...) -> bool`, `def is_presented_token_valid(env_name: str, presented: str) -> bool`(현재·이전 둘 중 하나와 상수 시간 비교, 둘 다 없으면 False)
- `app_attention_fetch.py`:
  - `FETCH_RESULTS = ("ok","not_modified","unauthorized","disabled","invalid","timeout","error")`
  - `@dataclass(frozen=True) class FetchOutcome`: result, document(object|None), etag(str|None), error_label(str|None)
  - `def fetch_attention(source, etag: str | None, http_get=requests.get) -> FetchOutcome`: `${ENV}` 치환(registry_loader의 치환 함수 재사용), 헤더 `X-Control-Token`(토큰 없으면 요청하지 않고 `unauthorized`/`token_missing`), `If-None-Match`, `stream=True, allow_redirects=False, timeout=source.timeout_seconds`, 65536 bytes 넘으면 `invalid`/`too_large`, 200 JSON 파싱 실패 `invalid`/`not_json`, 304 `not_modified`, 401/403 `unauthorized`, 404 `disabled`, 그 외 `error`/`http_<code>`, 예외는 `check_runner.classify_error`
- `app_attention_ingest.py`:
  - `class AppAttentionIngest`: `__init__(self, store, dispatcher, registry_provider, is_project_down: Callable[[str], bool])`
  - `def ingest(self, source, outcome: FetchOutcome, now) -> IngestReport` (`IngestReport(result, dropped_items, notification_count)`): 소스별 `threading.Lock` > 실패·not_modified는 상태만(`record_attention_failure`, not_modified는 성공 시각 갱신) > 검증(Task 1) > `generated_at <= state.last_generated_at`이면 버림 > 유효 항목(Task 3) > 평가 > `commit_attention_result(... expected_last_generated_at=읽은 값)` False면 버림 > 발송(`dispatcher.send`, 실패 로그만) > 연동 끊김/복구 평가·발송
  - `def preview(self, source, outcome) -> dict`: 연결 확인용, 저장·발송 없음. `{result, error_label, errors, dropped_items, items:[{key,label,kind,level,value 요약}]}`
- [ ] 테스트: 토큰 현재·이전 허용 / 둘 다 없으면 거부 / 이벤트 입구가 `_PREVIOUS` 수용, fetch 크기 초과·비JSON·304·401·404·timeout 분류(가짜 http_get), 첫 성공 기준선, Review Focus 3·5, 실패해도 항목 유지, preview가 DB를 바꾸지 않음
- [ ] 구현 > 통과 > 커밋

### Task 5: 폴러 단계

**Files:**
- Create: `service/control_tower/poller_app_attention.py`
- Modify: `service/control_tower/poller.py` (생성자 인자 `app_attention_step=None` + `tick()` 끝 호출 2줄), `service/control_tower/bootstrap.py` (step 생성·주입)
- Test: `test/test_control_tower_app_attention_poller.py`

**Interfaces:**
- `class AppAttentionStep`: `__init__(self, store, ingest: AppAttentionIngest, fetch=fetch_attention, monotonic=time.monotonic, max_workers=8, tick_budget_seconds=10)`; `def run(self, now) -> None`
  - 대상: `is_enabled` 이고 `mode != "push"` 이고 `last_attempt_at is None or last_attempt_at + interval - 5초 <= now`
  - 응답의 `poll_after_seconds`는 [60,3600]으로 잘라 interval과 비교해 큰 값 사용 (state에 반영할 필드가 필요하면 Task 2 state에 `next_due_at` 추가 가능 — 추가 시 Task 2 테스트도 보강)
  - 병렬 수집, 전체 `tick_budget_seconds` 넘으면 끝나지 않은 결과는 버리고 다음 틱(기다리지 않음: `concurrent.futures.wait(timeout=...)`)
  - push 전용 소스도 끊김 판정은 매 틱 수행(Task 3 `evaluate_source_health`)
  - 예외는 모두 삼키고 `logger.warning` (틱 보호)
- [ ] 테스트(가짜 fetch·시계): 주기 전엔 수집 안 함, 여유 5초 안이면 수집, push 전용은 수집 안 하지만 끊김 판정, 한 소스가 15초 걸려도 run이 10초 근처에서 반환하고 다른 소스는 처리됨(Review Focus 2), 예외가 틱 밖으로 안 나감
- [ ] 구현 > 통과 > 커밋

### Task 6: 디스코드 `attention` 채널 종류

**Files:**
- Modify: `service/control_tower/registry_models.py` (`PROJECT_CHANNEL_KINDS`에 `"attention"`, `DEFAULT_CHANNEL_NAMES["attention"]="확인할일"`, `DEFAULT_CHANNEL_VISIBILITY["attention"]=("dev",)`), `config/control_tower/services.yml` (`channel_visibility`에 `attention: [dev]`), `service/control_tower/discord_sync_plan.py` (attention 채널은 연동 소스가 있는 프로젝트에만 계획; 소스 없는 프로젝트의 기존 attention 채널은 보관(archive)하지 않음), 동기화 계획 함수가 소스 보유 프로젝트 id 집합을 받도록 호출부(`discord_sync.py`) 수정
- Test: `test/test_control_tower_app_attention_discord.py`

- [ ] 테스트: 소스 있는 프로젝트만 `확인할일` 채널 생성 계획, 공개 대상 dev+관리자, 소스를 지워도 기존 채널 보관 안 함, 기존 4종 채널 계획은 변화 없음(기존 discord sync 테스트 전부 통과), `EventDispatcher`가 `attention` kind로 채널을 찾고 없으면 `#관제-긴급` 대체
- [ ] 구현 > 통과 > 커밋

### Task 7: API, push 입구, nginx, overview·digest

**Files:**
- Create: `router/control_tower_app_attention_api.py` (관리 API 7개, 스펙 5.7), `router/control_tower_app_attention_intake.py` (push 입구), `service/control_tower/app_attention_view.py` (화면용 직렬화: 유효 항목, 소스 상태, 토큰 설정 여부, summary)
- Modify: blueprint 등록 위치(기존 manage API 등록과 같은 곳), `service/audit_service.py` (`AuditAction` 항목 추가: 소스 저장/삭제, 항목 덮어쓰기, 연결 확인), `service/control_tower/overview.py` (`app_attention_summary` 키 추가), `service/control_tower/digest.py` (섹션 1개), `suh-ai-server/config/nginx.conf` (`location = /api/flask/control/events`와 같은 방식으로 `location ^~ /api/flask/control/attention/` 키 예외, 같은 limit_req zone, `client_max_body_size 64k`), `test/test_control_tower_nginx.py` (예외 경로가 허용 목록 2개와 정확히 일치)
- Test: `test/test_control_tower_app_attention_api.py`

**Interfaces:**
- 소스 저장 검증: project_id는 유효 레지스트리(yml+관리 화면 추가)에 있어야 함(`unknown_project` 404), source_id 규칙, url은 https 또는 `http://` + (`${...}` 치환 대상 또는 사설 IP), mode, 숫자 범위
- push: 본문 64KB 초과 413, 소스 없음 404 `unknown_source`, `mode=="pull"` 403 `push_disabled`, 토큰 `CONTROL_EVENT_TOKEN_<PROJECT>`(+`_PREVIOUS`) 틀림 401, 처리는 `ingest`에 `FetchOutcome("ok", body, None, None)` 전달, 응답 202 `{result, dropped_items}`
- `app_attention_summary`: `{open_item_count, warning_count, critical_count, failing_source_count}` (숨김·ok·0건 제외)
- [ ] 테스트: 각 엔드포인트 성공·검증 실패, 삭제 cascade, 연결 확인이 저장 안 함, push 401/403/404/413/202, overview 키, digest 섹션, nginx 테스트
- [ ] 구현 > 통과 > 커밋

### Task 8: 화면

**Files:**
- Create: `templates/admin/control/app_attention.html`(현황 섹션), `templates/admin/control/app_attention_manage.html`(관리 모달/섹션), `static/js/control-app-attention.js`, `static/js/control-manage-app-attention.js`, `static/js/dashboard-app-attention.js`
- Modify: `templates/admin/control.html`(include, script 태그), `templates/admin/dashboard.html`(카드), `templates/admin/control/overview.html`·`manage.html`(include 1줄)
- 새 Tailwind 클래스가 필요하면 `frontend`에서 `npm run build` 후 `static/css/app.css` 함께 커밋. 임의값 클래스(`w-[7rem]` 등) 금지(빌드에 없음) — 필요하면 inline style
- [ ] 로컬 기동(가짜 소스) 후 `/pro-launch` 웹 캡처: 현황(항목 있음/없음/연동 끊김), 관리(소스 추가·연결 확인·항목 덮어쓰기), 대시보드 카드, 라이트·다크
- [ ] 커밋

### Task 9: 연동 가이드

**Files:**
- Create: `docs/control-tower/attention/README.md` (레포 루트 기준)
- 내용: 규격 요약(스키마 파일 링크), pull/push, 토큰 이름 규칙과 교체, 표준 key 표, 앱 관리자 화면 "관제소 연동" 섹션 요구, Spring 참조 구현(컨트롤러, 응답 record, 토큰 필터, 집계 재사용 예), 관제소 등록·연결 확인 절차, 하지 말 것(개인정보·본문 전달, key 변경, 0건 항목 생략)
- [ ] 커밋
