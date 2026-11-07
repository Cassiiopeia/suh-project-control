# SUH 관제소 1단계 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서비스가 죽으면 3분 안에 디스코드로 알리고, 집 밖 Cloudflare Worker가 공개 status 페이지와 관제소 심박 감시를 맡는다.

**Architecture:** Flask 서버(Windows) 안의 `service/control_tower/` 패키지가 등록 파일을 읽어 1분마다 내부 점검 → 상태 판정 → 디스코드 알림을 한다. 같은 틱에서 Cloudflare Worker로 심박을 보내고(집→밖 방향만), 응답으로 외부 점검 결과를 받아 판정에 합친다. Worker는 1분 크론으로 외부 점검·D1 기록·심박 끊김 비상 알림을 하고 `status.suhsaechan.kr`을 서빙한다.

**Tech Stack:** Python 3.10+ / Flask 3 / sqlite3(표준 라이브러리) / requests / PyYAML · Cloudflare Workers(JS, ES modules) + D1 + Cron Triggers · Discord REST API v10 · DaisyUI 관리자 화면(기존) · node --test(Worker 테스트, 외부 의존성 없음)

**Spec:** `docs/superpowers/specs/2026-11-05-control-tower-monitoring-design.md` (이슈 #148)

## Global Constraints

- 코드 주석·로그: 주석은 한국어 한 줄 요약/블록 머리글, 로그는 영어 + 접두사 `[control-tower ...]` (사용자 코딩 규칙 7장).
- 이름: boolean은 `is_/has_/can_/should_`, 약어 금지, 단위 접미사(`_seconds`, `_milliseconds`).
- 점검 간격 60초, 점검 타임아웃 10초, 느림 기준 5000ms, down 3회 연속 실패, 복구 2회 연속 성공, 재알림 6시간, 일일 요약 09:00 KST — 모두 등록 파일 `alert:` 기본값이며 코드에는 기본값만 둔다.
- 정상 판정 기본: HTTP 응답이 오고 502·503·504가 아니면 정상. `expect` 목록이 있으면 그 코드만 정상. 연결 실패·TLS 실패·타임아웃은 실패.
- 서비스 상태값: `active` / `paused` / `retired`. 응답이 없던 12개는 `paused`로 시작.
- 디스코드 권한·채널 이름·역할 이름은 등록 파일 설정. 기본값: `<project>`=상태·배포, `<project>-dev`=+에러·신고, `#관제-긴급`·`#관제-요약`=관리자만, `#공지`=모두.
- 동기화는 아무것도 삭제하지 않는다. 등록 파일에서 빠진 프로젝트 카테고리는 이름 앞에 `[보관] `을 붙이고 관리자만 보이게 한다.
- 시크릿·내부 IP는 레포에 넣지 않는다. 등록 파일 점검 주소는 `${ENV_NAME}` 치환을 지원하고 값은 `flask/.env`(GitHub Secret `FLASK_ENV_FILE`)에 둔다.
- 집↔Cloudflare 통신은 Flask가 Worker를 호출하는 방향만. Worker는 Flask를 호출하지 않는다.
- HMAC: 헤더 `X-CT-Timestamp`(unix 초), `X-CT-Signature` = hex(HMAC-SHA256(secret, `"{timestamp}.{raw_body}"`)), 허용 오차 300초.
- Worker 무료 한도: 크론 실행당 외부 요청 50개 → 외부 점검 대상은 최대 45개(등록 파일 검증에서 거부). D1 쓰기는 크론 1회당 1행 + 일별 집계.
- 공개 페이지·`/api/status.json`에는 `public: true` 이면서 `active`인 서비스만 나간다. 점검 URL·내부 주소·에러 본문은 나가지 않는다.
- Flask 외부 경로는 `/api/flask/...`(nginx). 이벤트 입구 `/api/flask/control/events`만 API 키 검사 예외.
- 감시 DB: `suh-ai-server/flask/data/control_tower.db` (`data/`는 이미 gitignore, 배포 scp `rm: false`라 유지됨).

## Review Focus

1. 관제소 재기동 직후: 메모리 상태가 비어 있어도 SQLite의 마지막 상태로 복원해서 "복구" 알림이 잘못 나가거나 진행 중 장애가 사라지면 안 된다 → Task 4·5에 테스트.
2. Worker에 닿지 못할 때(집 인터넷 끊김): 외부 결과를 "실패"가 아니라 "모름"으로 취급해야 40개 서비스 다운 알림이 쏟아지지 않는다 → Task 5에 테스트.
3. 디스코드 429·5xx: 알림 1건 실패가 폴러 틱 전체를 죽이거나 무한 재시도하면 안 된다(1회 재시도 후 기록) → Task 6에 테스트.
4. 등록 파일 오류(오타, 중복 id, 없는 부모): 배포 후 폴러가 조용히 멈추지 않고 기동 로그에 원인을 남기고 이전 정상 설정으로 계속 돈다 → Task 1·9에 테스트.
5. 점검 중(maintenance) 기간이 끝나는 순간 여전히 down인 서비스: 점검 종료 후 다음 틱에 down 알림 1회가 나가야 한다 → Task 5에 테스트.

---

### Task 0: 실측 확인과 서비스 위치 표 (운영 작업, 코드 없음)

**Files:**
- Create: `docs/control-tower/inventory.md` (IP·포트는 env 이름으로만 표기)

- [ ] **Step 1: 사용자 승인 받기** — `suh-ai-windows`, `synology-nas` 둘 다 `ask-first`. "읽기 전용 명령만 실행" 범위로 승인받는다.
- [ ] **Step 2: Windows NAS 의존성** — `/pro-ssh`로 `ipconfig /all`, `route print -4`. 기대: DNS 서버·기본 게이트웨이가 공유기 IP. NAS IP면 사용자에게 보고하고 "Windows DNS를 공유기/1.1.1.1로 변경"을 별도 승인 후 진행.
- [ ] **Step 3: DSM 역방향 프록시 규칙** — NAS에서 `sudo /usr/syno/bin/synowebapi --exec api=SYNO.Core.AppPortal.ReverseProxy method=list version=1`. 도메인 → 대상 호스트:포트 표 작성.
- [ ] **Step 4: Windows nginx·감사 DB 위치** — `ai.suhsaechan.kr` 규칙이 Windows `:11435`로 가는지 확인. `flask/.env`의 `AUDIT_DATABASE_URL`은 호스트 부분만 추출(`findstr`로 값 전체 출력 금지).
- [ ] **Step 5: inventory.md 작성 후 사용자에게 12개 `paused` 서비스 목록 재확인 요청(답 없어도 진행).**
- [ ] **Step 6: Commit** — `docs/control-tower/inventory.md`

### Task 1: 등록 파일 로더

**Files:**
- Create: `suh-ai-server/flask/service/control_tower/__init__.py`, `service/control_tower/registry.py`, `config/control_tower_config.py`, `config/control_tower/services.yml`
- Modify: `suh-ai-server/flask/requirements.txt` (`PyYAML==6.0.2` 추가)
- Test: `suh-ai-server/flask/test/test_control_tower_registry.py`

**Interfaces:**
- Produces (`registry.py`):
  - `@dataclass(frozen=True) CheckSpec(kind: str  # 'http'|'tcp', target: str, expect: tuple[int, ...] = (), timeout_seconds: int = 10)`
  - `@dataclass(frozen=True) ServiceSpec(id, name, project_id, status, is_public: bool, depends_on: str | None, internal: CheckSpec | None, external: CheckSpec | None)`
  - `@dataclass(frozen=True) ProjectSpec(id, name, channel_kinds: tuple[str, ...], channel_visibility: dict[str, tuple[str, ...]])`
  - `@dataclass(frozen=True) AlertPolicy(failures_to_down=3, successes_to_up=2, slow_milliseconds=5000, reminder_hours=6, digest_hour_kst=9)`
  - `@dataclass(frozen=True) DiscordPolicy(role_names: dict[str, str], channel_names: dict[str, str], global_channels: dict[str, tuple[str, ...]])`
  - `@dataclass(frozen=True) MaintenanceWindow(service_id, until: datetime, reason: str)`
  - `@dataclass(frozen=True) Registry(projects, services, infrastructure: tuple[ServiceSpec, ...], alert: AlertPolicy, discord: DiscordPolicy, maintenance: tuple[MaintenanceWindow, ...])` with `service_by_id(id) -> ServiceSpec | None`, `children_of(parent_id) -> tuple[ServiceSpec, ...]`, `to_worker_snapshot() -> dict`, `version() -> str` (sha256 hex of canonical JSON snapshot)
  - `class RegistryError(Exception)` (message lists every problem, one per line)
  - `load_registry(path: str, environ: Mapping[str, str]) -> Registry`
- Produces (`control_tower_config.py`): `REGISTRY_PATH`, `DATABASE_PATH`, `POLL_INTERVAL_SECONDS = 60`, `WORKER_URL_ENV = 'CONTROL_TOWER_WORKER_URL'`, `HMAC_SECRET_ENV = 'CONTROL_TOWER_HMAC_SECRET'`, `DISCORD_BOT_TOKEN_ENV`, `DISCORD_GUILD_ID_ENV`, `EVENT_TOKEN_ENV_PREFIX = 'CONTROL_EVENT_TOKEN_'`, `MAX_EXTERNAL_CHECKS = 45`

- [ ] **Step 1: Write failing tests**

```python
def test_loads_defaults_and_inherits_project(tmp_path): ...
    # services.yml 최소 예시 → alert.failures_to_down == 3, service.project_id == 'elum'
def test_substitutes_env_placeholders(tmp_path):
    # target 'http://${NAS_LAN_HOST}:8079/healthz' + environ {'NAS_LAN_HOST': '10.0.0.5'} → 'http://10.0.0.5:8079/healthz'
def test_missing_env_placeholder_is_error(tmp_path):
    # RegistryError, 메시지에 'NAS_LAN_HOST' 포함
def test_rejects_duplicate_ids_unknown_parent_and_bad_status(tmp_path):
    # 세 문제가 한 RegistryError 메시지에 모두 나온다
def test_rejects_more_than_45_external_checks(tmp_path): ...
def test_project_channel_visibility_overrides_global_default(tmp_path):
    # 전역 error:[dev], elum만 error:[member, dev] → elum ProjectSpec.channel_visibility['error'] == ('member','dev'), 다른 프로젝트는 ('dev',)
def test_worker_snapshot_excludes_internal_checks_and_secrets(tmp_path):
    # snapshot 서비스에 'internal' 키 없음, external.url·expect·timeout_seconds·is_public·status만
def test_version_changes_when_snapshot_changes(tmp_path): ...
```

- [ ] **Step 2: Run** `cd suh-ai-server/flask && python -m pytest test/test_control_tower_registry.py -v` → FAIL (module not found)
- [ ] **Step 3: Implement `load_registry`** — YAML 구조는 스펙 5.1·5.6 예시 그대로. `${NAME}` 치환은 `re.sub(r'\$\{([A-Z0-9_]+)\}')`. 모든 검증 오류를 모아 한 번에 raise.
- [ ] **Step 4: 실제 `services.yml` 초안 작성** — Task 0 inventory 기준. 프로젝트 묶음은 서브도메인 이름 기준, 관리 도구(mongo, pgadmin, rabbitmq, minio, qdrant, nexus, traefik, s3, server)는 `infra` 프로젝트·비공개, 응답 없던 12개 `paused`, 인프라 `nas`(tcp `${NAS_LAN_HOST}:5001`), `windows`(점검 없음, 관제소 자신), `home-network`(점검 없음). 검증용 `control-tower-canary`(`infra`, internal http `http://127.0.0.1:18080/`, 비공개, `active`). 테스트 추가: `test_repository_registry_file_loads(monkeypatch)` — 실제 파일이 placeholder 더미 env로 로드된다.
- [ ] **Step 5: Run tests** → PASS
- [ ] **Step 6: Commit**

### Task 2: 점검 실행과 판정 규칙

**Files:**
- Create: `service/control_tower/check_runner.py`
- Test: `test/test_control_tower_check_runner.py`

**Interfaces:**
- Consumes: `CheckSpec`
- Produces: `@dataclass(frozen=True) CheckResult(is_ok: bool, is_slow: bool, status_code: int | None, latency_milliseconds: int, error: str | None, checked_at: datetime)`; `run_check(spec: CheckSpec, slow_milliseconds: int, http_get=requests.get, open_socket=socket.create_connection, now=utcnow) -> CheckResult`; `is_status_ok(status_code: int, expect: tuple[int, ...]) -> bool`

- [ ] **Step 1: Write failing tests**

```python
@pytest.mark.parametrize('code, expect, ok', [
    (200, (), True), (401, (), True), (404, (), True), (500, (), True),
    (502, (), False), (503, (), False), (504, (), False),
    (404, (200,), False), (200, (200,), True)])
def test_is_status_ok(code, expect, ok): ...
def test_http_timeout_is_failure_with_error_label():   # error == 'timeout'
def test_connection_error_is_failure():                # error == 'connection_error'
def test_slow_response_marks_is_slow_but_ok():         # latency 6000 > 5000 → is_ok True, is_slow True
def test_tcp_check_success_and_refused():
def test_http_check_does_not_follow_redirects():       # http_get 호출 인자 allow_redirects=False
```

- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** — `requests.get(url, timeout=spec.timeout_seconds, allow_redirects=False)`; 예외는 `timeout` / `tls_error` / `connection_error` / `error` 4종 라벨로만 기록(외부 메시지 원문 저장 금지).
- [ ] **Step 4: Run** → PASS
- [ ] **Step 5: Commit**

### Task 3: 상태 기계 (순수 함수)

**Files:**
- Create: `service/control_tower/state_machine.py`
- Test: `test/test_control_tower_state_machine.py`

**Interfaces:**
- Consumes: `CheckResult`, `AlertPolicy`
- Produces:
  - `@dataclass(frozen=True) Observation(internal: CheckResult | None, external: CheckResult | None, is_external_known: bool)`
  - `@dataclass(frozen=True) ServiceState(status: str  # 'up'|'degraded'|'down'|'unknown', consecutive_failures: int, consecutive_successes: int, cause: str | None  # 'service_down'|'external_path'|'unreachable', since: datetime | None, last_notified_at: datetime | None, is_down_notified: bool)`
  - `@dataclass(frozen=True) Transition(service_id: str, before: str, after: str, cause: str | None, since: datetime)`
  - `advance(service_id, previous: ServiceState, observation: Observation, policy: AlertPolicy, now: datetime) -> tuple[ServiceState, Transition | None]`
  - `INITIAL_STATE = ServiceState('unknown', 0, 0, None, None, None, False)`

- [ ] **Step 1: Write failing tests**

```python
def test_three_consecutive_failures_go_down_with_since_at_first_failure(): ...
def test_two_failures_then_success_stays_up(): ...
def test_two_successes_needed_to_recover(): ...
def test_cause_external_path_when_internal_ok_external_fails(): ...
def test_cause_service_down_when_both_fail(): ...
def test_cause_unreachable_when_only_external_configured_and_fails(): ...
def test_unknown_external_is_ignored_not_failure():
    # internal ok, is_external_known False → up 유지 (Review Focus 2)
def test_slow_but_ok_is_degraded_and_back_to_up(): ...
def test_unknown_initial_to_up_emits_no_transition():
    # 기동 직후 첫 성공은 알림 대상 전이가 아니다
```

- [ ] **Step 2: Run** → FAIL · **Step 3: Implement** · **Step 4: Run** → PASS · **Step 5: Commit**

### Task 4: SQLite 저장소

**Files:**
- Create: `service/control_tower/store.py`
- Test: `test/test_control_tower_store.py`

**Interfaces:**
- Produces `class ControlTowerStore(path: str)`:
  - `initialize() -> None` (테이블 `check_result`, `daily_rollup`, `incident`, `service_state`, `event_log`, `discord_binding`, `maintenance_override`, `meta`; `PRAGMA journal_mode=WAL`; 스레드마다 연결)
  - `save_results(service_id, observation: Observation, now) -> None` (원시 + 일별 집계 UPSERT, KST 날짜 기준)
  - `load_states() -> dict[str, ServiceState]` / `save_state(service_id, state) -> None`
  - `open_incident(service_id, cause, started_at) -> int` / `close_incident(service_id, ended_at) -> int | None` / `recent_incidents(limit, since) -> list[dict]`
  - `uptime_by_day(service_id, days: int) -> list[tuple[str, int, int]]`
  - `record_event(project_id, kind, dedupe_key, created_at) -> bool` (10분 내 같은 key면 False)
  - `get_binding(scope, kind) -> str | None` / `set_binding(scope, kind, discord_id) -> None`
  - `get_meta(key) -> str | None` / `set_meta(key, value) -> None`
  - `set_maintenance(service_id, until, reason)` / `clear_maintenance(service_id)` / `active_maintenance(now) -> dict[str, MaintenanceWindow]`
  - `purge(now) -> None` (check_result 7일, event_log 30일, daily_rollup 400일)

- [ ] **Step 1: Write failing tests** — `tmp_path` DB로: 상태 저장·재로드 왕복(Review Focus 1), 장애 열고 닫기 + 중복 open 방지, 일별 집계가 KST 자정 기준으로 나뉨(UTC 15:00 경계), dedupe 10분, purge 경계, 바인딩 덮어쓰기.
- [ ] **Step 2: Run** → FAIL · **Step 3: Implement** · **Step 4: Run** → PASS · **Step 5: Commit**

### Task 5: 알림 계획 (부모 묶음·점검 중·재알림)

**Files:**
- Create: `service/control_tower/alert_planner.py`
- Test: `test/test_control_tower_alert_planner.py`

**Interfaces:**
- Consumes: `Registry`, `ServiceState`, `Transition`, `MaintenanceWindow`
- Produces:
  - `@dataclass(frozen=True) Notification(scope: str  # project id | 'global', kind: str  # 'status'|'alert'|'digest', severity: str, title: str, body: str, service_ids: tuple[str, ...], dedupe_key: str)`
  - `plan_notifications(registry, states: dict[str, ServiceState], transitions: list[Transition], maintenance: dict[str, MaintenanceWindow], now: datetime) -> tuple[list[Notification], dict[str, ServiceState]]` (두 번째 값: `is_down_notified`/`last_notified_at`이 갱신된 상태)

규칙(테스트가 고정):
- `paused`/`retired` 서비스는 알림 없음. 인프라(`nas` 등) 알림은 scope `global`, kind `alert`. 프로젝트 서비스는 scope=project, kind `status`.
- 부모가 down이면 자식 down 전이는 개별 알림 없이 부모 알림 body에 "영향 서비스 N개"와 이름 목록으로 들어간다.
- 부모 복구 후에도 down인 자식은 다음 계획 호출에서 개별 down 알림 1회(`is_down_notified` False인 down 상태).
- 점검 중 서비스는 알림 없음. 점검 종료 후 여전히 down이고 `is_down_notified` False면 알림 1회(Review Focus 5).
- down 지속 중 `last_notified_at`에서 `reminder_hours` 지나면 재알림(제목에 "계속 다운").
- 복구 알림 body에 다운 시간(`1시간 12분` 형식).
- `home-network` down(심박 실패) 중에는 외부 원인(`external_path`, `unreachable`) 알림을 만들지 않는다.

- [ ] **Step 1: Write failing tests** — 위 규칙마다 1개 이상. 핵심: `test_nas_down_sends_one_alert_listing_children`, `test_child_still_down_after_parent_recovers_alerts_once`, `test_maintenance_end_while_down_alerts_once`, `test_reminder_after_six_hours`, `test_recovery_body_has_duration`, `test_paused_service_never_alerts`, `test_restart_with_restored_down_state_does_not_resend` (load된 상태 `is_down_notified=True` → 알림 없음).
- [ ] **Step 2–4: FAIL → Implement → PASS** · **Step 5: Commit**

### Task 6: 디스코드 클라이언트와 메시지 형식

**Files:**
- Create: `service/control_tower/discord_client.py`, `service/control_tower/discord_messages.py`
- Test: `test/test_control_tower_discord_client.py`, `test/test_control_tower_discord_messages.py`

**Interfaces:**
- Produces (`discord_client.py`): `class DiscordClient(bot_token: str, guild_id: str, session=requests.Session(), sleep=time.sleep)` with `send_embed(channel_id, embed: dict) -> bool`, `list_channels() -> list[dict]`, `create_channel(name, channel_type: int, parent_id: str | None, overwrites: list[dict]) -> dict`, `edit_channel(channel_id, **fields) -> dict`, `list_roles() -> list[dict]`, `create_role(name) -> dict`, `put_onboarding(payload: dict) -> bool`; `class DiscordError(Exception)`. Base URL `https://discord.com/api/v10`, 헤더 `Authorization: Bot {token}`.
- Produces (`discord_messages.py`): `to_embed(notification: Notification, status_page_url: str) -> dict` — 색 down `0xE5484D`, recovered `0x30A46C`, degraded `0xF5A524`, info `0x8B8D98`; title ≤ 256자, description ≤ 4000자로 자름.

- [ ] **Step 1: Write failing tests** — 429 응답(`retry_after: 1.5`)이면 1.5초 sleep 후 1회 재시도, 두 번째도 실패면 `send_embed` False(예외 없음, Review Focus 3); 5xx 1회 재시도; 401은 재시도 없이 `DiscordError`(채널 관리 메서드) / False(send). 메시지: 길이 자르기, 색 매핑, 복구 임베드에 다운 시간 필드.
- [ ] **Step 2–4** · **Step 5: Commit**

### Task 7: 디스코드 구조 동기화

**Files:**
- Create: `service/control_tower/discord_sync.py`
- Test: `test/test_control_tower_discord_sync.py`

**Interfaces:**
- Consumes: `Registry`, `DiscordClient`, `ControlTowerStore`
- Produces:
  - `plan_sync(registry, current_channels: list[dict], current_roles: list[dict], guild_id: str, bindings: dict[tuple[str, str], str]) -> list[SyncOperation]` (순수)
  - `@dataclass(frozen=True) SyncOperation(action: str  # 'create_role'|'create_category'|'create_channel'|'update_channel'|'archive_category', scope: str, kind: str | None, name: str, target_id: str | None, overwrites: tuple[dict, ...])`
  - `apply_sync(client, store, operations) -> SyncReport` / `@dataclass SyncReport(created: int, updated: int, archived: int, errors: list[str], is_onboarding_applied: bool)`
  - `build_onboarding_payload(registry, role_ids_by_project: dict[str, str]) -> dict`

규칙: 권한 덮어쓰기 = `@everyone`(id=guild_id) VIEW_CHANNEL(1024) deny + 허용 역할 allow + 관리자 역할 allow. `everyone` 공개 채널은 deny 없음. 기존 채널은 바인딩 ID 우선, 없으면 같은 카테고리 안 같은 이름으로 찾음. 관리자가 준 개인(type=1) 덮어쓰기는 유지. 등록 파일에서 빠진 카테고리 → `[보관] ` 접두사 + 관리자만.

- [ ] **Step 1: Write failing tests** — 빈 서버 → 전역 채널 3 + 프로젝트별 카테고리·채널·역할 2개 생성 계획; 두 번째 실행은 변경 없음(멱등); elum `error` 덮어쓰기가 `member` 역할 allow 포함; 개인 덮어쓰기 보존; 빠진 프로젝트 보관; onboarding payload에 프로젝트별 옵션 1개(`role_ids=[member role]`), `single_select False`, `required False`.
- [ ] **Step 2–4** · **Step 5: Commit**

### Task 8: 이벤트 입구와 라우팅

**Files:**
- Create: `service/control_tower/event_dispatcher.py`, `router/control_tower_router.py`
- Modify: `app.py` (블루프린트 등록), `suh-ai-server/config/nginx.conf` (`location = /api/flask/control/events` 키 검사 없이 Flask로)
- Test: `test/test_control_tower_events.py`

**Interfaces:**
- Produces (`event_dispatcher.py`): `class EventDispatcher(registry_provider, store, discord_client_provider, status_page_url)` with `dispatch(notification: Notification) -> bool` (scope·kind → 바인딩 채널, 없으면 global alert 채널 + 경고 로그), `accept_event(project_id, payload: dict, now) -> tuple[int, dict]`
- Produces (router): `control_tower_bp`; `POST /control/events` — 헤더 `X-Control-Token`, env `CONTROL_EVENT_TOKEN_<PROJECT_ID 대문자, '-'→'_'>`와 `hmac.compare_digest`.

응답 고정: 202 `{"accepted": true, "deduplicated": false}` / 중복 202 `{"accepted": true, "deduplicated": true}` / 토큰 불일치 401 `{"error": "unauthorized"}` / 모르는 프로젝트 404 / 검증 실패 400 `{"error": "invalid", "fields": [...]}`. 검증: kind ∈ {report, error, deploy, status, info}, severity ∈ {info, warning, critical}, title 1–200자, body ≤ 2000자, url은 `https://`만.

- [ ] **Step 1: Write failing tests** — 위 응답 6종, 토큰 env 없는 프로젝트는 401, 채널 바인딩 없으면 global alert로 감, nginx.conf에 정확히 그 경로 예외가 있는지 문자열 검사(`test_nginx_exempts_only_event_intake`).
- [ ] **Step 2–4** · **Step 5: Commit**

### Task 9: 심박 클라이언트·폴러·일일 요약 연결

**Files:**
- Create: `service/control_tower/heartbeat_client.py`, `service/control_tower/poller.py`, `service/control_tower/digest.py`
- Modify: `run.py` (폴러 시작, 기존 폴러 블록과 같은 형태)
- Test: `test/test_control_tower_heartbeat.py`, `test/test_control_tower_poller.py`, `test/test_control_tower_digest.py`

**Interfaces:**
- Produces (`heartbeat_client.py`): `sign(secret: str, timestamp: int, raw_body: bytes) -> str`; `class HeartbeatClient(worker_url, secret, session)` with `send(registry: Registry, public_incidents: list[dict], now) -> HeartbeatResponse | None` — `POST {worker_url}/api/heartbeat` body `{"sent_at", "config_version", "public_incidents"}`; 응답 `need_config: true`면 같은 요청에 `"config": registry.to_worker_snapshot()`를 넣어 1회 재전송. `@dataclass HeartbeatResponse(external_results: dict[str, CheckResult], checked_at: datetime | None)`. 실패 시 None.
- Produces (`poller.py`): `class ControlTowerPoller(registry_path, store, dispatcher, heartbeat_client, check_runner=run_check, now=utcnow, interval_seconds=60)` with `start() -> threading.Thread`, `tick() -> None`. 틱 순서: 등록 파일 재로드(실패 시 이전 Registry 유지 + 오류 로그, Review Focus 4) → 심박(3회 연속 실패면 `home-network` down 관측) → 내부 점검 병렬(ThreadPoolExecutor, max 16) → `advance` → `plan_notifications` → dispatch → 저장 → 장애 open/close → 09시 요약 → 하루 1회 purge.
- Produces (`digest.py`): `build_daily_digest(registry, store, day_kst: date) -> Notification` (scope global, kind digest: 전날 서비스별 가동률 < 100%인 것만 나열, 장애 건수·총 다운 시간).

- [ ] **Step 1: Write failing tests** — sign 값이 고정 벡터와 일치(Worker 테스트와 같은 벡터: secret `test-secret`, ts `1793750400`, body `{"a":1}`); need_config 재전송; 외부 결과 매핑; 폴러 한 틱에 가짜 점검·디스패처로 NAS down → 알림 1건; 등록 파일 깨진 상태로 틱 → 이전 설정으로 계속(예외 없음); 요약은 09:00 KST 이후 하루 1회만.
- [ ] **Step 2–4** · **Step 5: Commit**

### Task 10: 관리자 화면 `/admin/control`

**Files:**
- Create: `templates/admin/control.html`, `static/js/control.js`
- Modify: `router/admin_router.py` (`/admin/control`, `active='control'`), `templates/admin/base.html` (메뉴 "관제소", 아이콘 `radar`), `router/control_tower_router.py`
- Test: `test/test_admin_router.py`(추가), `test/test_control_tower_admin_api.py`

**Interfaces:**
- API (전부 nginx API 키 보호): `GET /control/overview` → `{"services": [{id, name, project_id, status, cause, since, internal, external, is_public, lifecycle}], "incidents": [...], "events": [...], "registry_error": str|null, "heartbeat": {"last_ok_at", "is_ok"}, "onboarding": {"is_applied"}}`; `POST /control/discord/sync` → `SyncReport` JSON; `POST /control/test-alert` `{"scope": "global"|project_id}` → `{"sent": bool}`; `POST /control/maintenance` `{"service_id", "until", "reason"}`; `DELETE /control/maintenance/<service_id>`.
- 화면: 기존 DaisyUI 레이아웃. 상단 요약(정상/장애/점검/확인 필요 수), 진행 중 장애 목록, 프로젝트별 서비스 표(상태 배지, 내부/외부 결과, 마지막 점검), `paused` 서비스는 "확인 필요" 배지, 최근 이벤트, 버튼(디스코드 동기화, 테스트 알림, 점검 중 설정). 30초마다 overview 재조회.

- [ ] **Step 1: Write failing tests** — 페이지 렌더·메뉴 링크(기존 `test_claude_login_page_renders` 형태), overview 형태, maintenance 설정/해제, 잘못된 until(과거·형식 오류) 400.
- [ ] **Step 2–4** · **Step 5: 로컬 실행 확인** — `cd suh-ai-server/flask && python app.py` 후 `/pro-launch` web으로 `http://127.0.0.1:5000/admin/control` 캡처(라이트·다크) · **Step 6: Commit**

### Task 11: Worker 핵심 (점검·심박·비상 알림·D1)

**Files:**
- Create: `control-tower-worker/package.json` (`"type": "module"`, scripts `test: node --test`), `wrangler.toml`, `migrations/0001_init.sql`, `src/index.js`, `src/hmac.js`, `src/checks.js`, `src/heartbeat.js`, `src/scheduled.js`, `src/store.js`
- Test: `control-tower-worker/test/hmac.test.js`, `checks.test.js`, `heartbeat.test.js`, `scheduled.test.js`

**Interfaces:**
- D1 테이블: `meta(key TEXT PRIMARY KEY, value TEXT)` (keys: `last_heartbeat_at`, `emergency_state` ok|down, `emergency_since`, `config_json`, `config_version`, `public_incidents_json`, `last_rollup_day`), `check_run(id INTEGER PRIMARY KEY, checked_at TEXT, results_json TEXT)`, `daily_rollup(day TEXT, service_id TEXT, total INTEGER, ok INTEGER, PRIMARY KEY(day, service_id))`.
- `hmac.js`: `sign(secret, timestamp, rawBody) -> Promise<string>`, `verify(secret, headers, rawBody, nowSeconds) -> Promise<boolean>` (오차 300초).
- `checks.js`: `isStatusOk(code, expect)` (Python과 같은 표), `runChecks(services, fetchImpl, nowMs) -> Promise<Result[]>` — `fetch(url, {redirect: 'manual', signal: AbortSignal.timeout(timeout_seconds*1000)})`, `external` 있는 `active`·`paused` 서비스만.
- `heartbeat.js`: `handleHeartbeat(request, env, now)` → 서명 실패 401; `last_heartbeat_at` 갱신; `emergency_state=down`이면 복구 웹훅 1회 + ok로; body `config_version` ≠ 저장값이고 `config` 없으면 `{"need_config": true}`; `config` 있으면 저장; 응답 `{"need_config": false, "checked_at", "external_results": {service_id: {is_ok, is_slow, status_code, latency_milliseconds, error}}}`(최신 check_run).
- `scheduled.js`: `runScheduled(env, nowMs, fetchImpl)` — 외부 점검 → check_run 1행 → 심박 3분 초과 && state ok → `DISCORD_EMERGENCY_WEBHOOK_URL`로 "관제소 심박 끊김(마지막 HH:MM KST). 집 인터넷, Windows 서버, NAS 중 하나 장애 가능" + state down → KST 날짜가 바뀌었으면 전날 rollup 기록 + check_run 7일 초과 삭제.
- `index.js`: `fetch` 라우팅(`POST /api/heartbeat`, `GET /api/status.json`, `GET /`), `scheduled` → `runScheduled`.
- `wrangler.toml`: `name = "suh-control-tower"`, `main = "src/index.js"`, `compatibility_date = "2026-10-01"`, `[triggers] crons = ["* * * * *"]`, D1 binding `DB` (database_name `suh-control-tower`), route `status.suhsaechan.kr` custom_domain = true.

- [ ] **Step 1: Write failing tests** — hmac 고정 벡터(Task 9와 같은 값), 시간 오차 301초 거부; isStatusOk 표(Task 2와 같은 9행); 심박 need_config 왕복; 비상 알림은 끊긴 동안 1회만, 복구 1회만; 가짜 D1(`Map` 기반 `prepare().bind().run()/all()/first()` 스텁)으로 rollup이 하루 1회만.
- [ ] **Step 2: Run** `cd control-tower-worker && node --test` → FAIL · **Step 3: Implement** · **Step 4: PASS** · **Step 5: Commit**

### Task 12: 공개 status 페이지

**Files:**
- Create: `control-tower-worker/src/status_page.js`
- Test: `control-tower-worker/test/status_page.test.js`

**Interfaces:**
- `buildStatusModel(configJson, checkRuns, rollups, publicIncidents, lastHeartbeatAt, nowMs) -> Model` (순수): 공개·active 서비스만, 프로젝트별 묶음, 현재 상태 = 최근 `failures_to_down`회 모두 실패면 down / 최근 1회 실패 또는 느림이면 degraded / 아니면 up / 데이터 없으면 unknown, 점검 중이면 maintenance. 90일 막대 = rollup 가동률(≥99.5% 초록, ≥95% 노랑, <95% 빨강, 없음 회색) + 오늘은 check_run으로 계산. 심박 3분 초과면 `isDelayed: true`.
- `renderStatusPage(model) -> string` (HTML): 제목 "SUH 서비스 상태", 전체 배너(모두 정상 / 일부 장애 / 점검 중), 지연 배너 문구 "일부 서비스 상태 확인이 지연되고 있습니다", 프로젝트별 카드, 서비스 행(이름·상태·90일 막대·90일 가동률), 최근 14일 장애, 마지막 갱신(KST). 인라인 CSS, `:root` 색 토큰 + `prefers-color-scheme: dark`, 폭 360px에서 가로 스크롤 없음, 외부 스크립트 없음.
- `/api/status.json` = Model을 그대로(같은 필터).

- [ ] **Step 1: Write failing tests** — 비공개·paused 서비스가 HTML·JSON 어디에도 없음(서비스 id·URL 문자열 검색); 내부 IP 형태 문자열(`192.168.`, `10.`) 없음; 상태 판정 4가지; 지연 배너; 막대 색 경계값(99.5, 95).
- [ ] **Step 2–4** · **Step 5: 로컬 확인** — `npx wrangler dev --local` 후 `/pro-launch` web으로 데스크톱·모바일 폭 캡처 · **Step 6: Commit**

### Task 13: Worker 배포 워크플로

**Files:**
- Create: `.github/workflows/CONTROL-TOWER-WORKER-DEPLOY.yaml`

- [ ] **Step 1: 워크플로 작성** — `on: push: branches [main], paths ['control-tower-worker/**']` + `workflow_dispatch`. 단계: checkout → `node --test`(working-directory) → `cloudflare/wrangler-action@v3` (`apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}`, `accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}`, `workingDirectory: control-tower-worker`, `command: deploy`) → 같은 액션으로 `d1 migrations apply suh-control-tower --remote`.
- [ ] **Step 2: Commit**

### Task 14: 외부 준비 (디스코드·Cloudflare·시크릿) — 운영 작업

모든 브라우저 작업은 `/pro-launch`. 값은 화면에 출력하지 않고 `web value|clipboard --save-env`로 받아 `cred set`·`secrets set`으로 바로 넣는다.

- [ ] **Step 1: 디스코드** — `cred` `discord-chan4760`(사용자가 저장)로 로그인(새 IP 메일 코드는 `gmail-imap-chan4760`로 읽기 전용 확인 또는 사용자에게 요청). 서버 "SUH 관제소" 생성 → 커뮤니티 전환(규칙 채널, 인증 수준 낮음) → Developer Portal에서 봇 앱 "SUH 관제소" 생성, 토큰 발급 → 권한 `Manage Channels, Manage Roles, View Channels, Send Messages, Embed Links`로 서버 초대 → 관리자 역할 생성·본인 부여. 확인: 봇이 멤버 목록에 있음.
- [ ] **Step 2: Cloudflare** — `cloudflare-chan4760`(ask-first, 사용자 승인 후) 프로필로: API 토큰 생성(권한 `Workers Scripts:Edit`, `D1:Edit`, `Workers Routes:Edit`(suhsaechan.kr 존), `Account Settings:Read`), D1 `suh-control-tower` 생성 → `wrangler.toml` database_id 기입·커밋. `status.suhsaechan.kr`은 Worker custom domain이 DNS 레코드를 만든다(첫 배포 시).
- [ ] **Step 3: 시크릿** — GitHub Secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`; `FLASK_ENV_FILE` 전체 갱신(기존 내용 유지 + `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `CONTROL_TOWER_HMAC_SECRET`, `CONTROL_TOWER_WORKER_URL=https://status.suhsaechan.kr`, `NAS_LAN_HOST` 등 Task 0의 env, `CONTROL_EVENT_TOKEN_ELUM`); Worker secret `HMAC_SECRET`(같은 값), `DISCORD_EMERGENCY_WEBHOOK_URL`(`#관제-긴급` 웹훅, Task 15 동기화 후 발급). 기존 `FLASK_ENV_FILE` 내용은 서버의 현재 `.env`와 비교해 키 누락이 없는지 키 이름만 대조.

### Task 15: 배포와 실측 검증

- [ ] **Step 1: 전체 테스트** — `cd suh-ai-server/flask && python -m pytest -q`, `cd control-tower-worker && node --test` 모두 PASS.
- [ ] **Step 2: 푸시 → PR(develop) → `/pro-changelog-deploy`** (서버 배포, 사용자 위임 범위 확인).
- [ ] **Step 3: 동기화** — 관리자 화면 "디스코드 동기화" → 채널·역할·온보딩 생성 확인(디스코드 캡처). `#관제-긴급` 웹훅 발급 → Worker secret 등록.
- [ ] **Step 4: 정상 흐름** — `status.suhsaechan.kr` 200, 공개 서비스만 표시; 관리자 화면 심박 `is_ok`.
- [ ] **Step 5: 장애 흐름 (사용자 승인 후)** — ① 카나리: 등록 파일의 `control-tower-canary`(`infra` 프로젝트, Windows에서 `python -m http.server 18080`로 띄운 대상, 내부 점검만, `depends_on` 없음) 프로세스 종료 → 3분 내 `infra` `#상태`에 down 알림, 재기동 후 복구 알림. ② Flask 서비스 NSSM stop → 4분 내 `#관제-긴급`에 Worker 비상 알림 → start 후 복구 알림.
- [ ] **Step 6: `/pro-report`로 보고서 댓글 → `finish-issue`**. 카나리 서비스는 `retired`로 바꾸거나 유지 여부를 사용자에게 확인.
