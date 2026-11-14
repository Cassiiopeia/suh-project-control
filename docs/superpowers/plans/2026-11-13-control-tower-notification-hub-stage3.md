# 관제소 알림 허브 3단계 구현 계획: Apprise 벤더링 + 추가 받을 곳 등록

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 프로젝트 알림을 SUH 관제소 Discord 채널 외에 팀 Discord 웹훅·슬랙·텔레그램·이메일 등으로도 보낸다. 받을 곳은 관리 화면에서 프로젝트·알림 종류별로 등록하고, 앱 코드는 바뀌지 않는다.

**Architecture:** Apprise(BSD-2) 소스를 `suh-ai-server/flask/vendor/apprise/`로 복사해 우리 코드로 쓴다. 받을 곳 URL은 `CONTROL_TOWER_SECRET`으로 암호화해 DB에 둔다. `EventDispatcher.dispatch`가 프로젝트 알림을 기본 Discord 채널로 보낸 뒤, 같은 (프로젝트, 채널 종류)에 등록된 받을 곳으로 백그라운드에서 퍼뜨린다. 기본 발송과 받을 곳 발송은 서로 막지 않는다.

**Tech Stack:** Python 3 / Flask / SQLite / vendored Apprise v2.2.0 / pytest / 바닐라 JS

**Spec:** `docs/superpowers/specs/2026-11-13-control-tower-notification-hub-design.md` (5.4, 6장 3단계)

## Global Constraints

- 원본: https://github.com/caronc/apprise 태그 `v2.2.0` (커밋 `58e42d2fc826adcb3be35272df34d3888d061b34`), BSD-2-Clause. 스크래치 복사본: `/tmp/apprise-vendor-src/apprise` (이미 clone됨, 여기서만 복사)
- 위치: `suh-ai-server/flask/vendor/apprise/` = 원본 `apprise/` 패키지 폴더 그대로 + 원본 `LICENSE`. 테스트·문서·packaging 제외. `vendor/__init__.py`, `vendor/apprise/VENDORED.md`(원본 주소·태그·커밋·복사 날짜·고친 목록)
- **첫 커밋은 원본 그대로 복사만.** 수정(절대 import 1곳 `utils/format.py:34 from apprise.common` 등)은 다음 커밋부터
- import 경로: `vendor.apprise`. 원본 의존성 중 없는 것만 `requirements.txt`에 버전 고정 추가 (`markdown`, `requests-oauthlib`, `click`, `certifi` 확인; `requests`·`PyYAML`은 이미 있음)
- 적용 범위: 관제소의 모든 **프로젝트** 알림(앱 이벤트 + 감시 다운·복구·지연 + attention). 전역(`global`) 알림은 제외. 퍼뜨리는 지점은 `EventDispatcher.dispatch` 한 곳
- 받을 곳은 (project_id, kind) 단위. kind = dispatch가 쓰는 채널 종류(`info` 이벤트는 `status`)와 같은 값. 기본 5종·사용자 정의 종류 모두 가능
- URL 암호화: 기존 `claude_login_secret_cipher`(PBKDF2 > AES-256-GCM)를 범용 이름의 모듈로 정리해 두 기능이 같은 함수를 씀. 받을 곳 키 = `CONTROL_TOWER_SECRET`. 화면에는 수단과 끝 4자리만 (`discord://…ab12`)
- 발송 실패: 기록(`last_result`, `last_sent_at`) + 경고 로그, 재시도 없음. 받을 곳 하나의 실패·지연이 다른 받을 곳·기본 Discord 발송·요청 응답을 막지 않음 (백그라운드)
- 기본 SUH 관제소 채널을 끄는 옵션 없음
- `CONTROL_TOWER_SECRET` 없음: 받을 곳 등록·수정 불가(409 `secret_not_configured`), 이미 있는 받을 곳은 발송 생략 + 경고(간격 제한, 2단계와 같은 방식)
- 코드 규칙·커밋 규칙은 1·2단계와 같음 (로그 접두사 `[control-tower deliver]`, `[control-tower destination]`)

## Review Focus

1. URL 원문이 DB·로그·감사·manage 응답·오류 메시지에 남지 않음 (Apprise 예외 메시지에 URL이 섞일 수 있음 > 정리 후 기록) (Task 2, 3)
2. 받을 곳 발송이 느리거나 실패해도 `/control/events` 202 응답 시간과 기본 Discord 발송은 그대로 (Task 2)
3. Apprise가 해석 못 하는 URL 등록 > 400, 저장 안 함 (Task 3)
4. 전역 알림(`#관제-긴급` 대체 포함)은 받을 곳으로 가지 않음 (Task 2)
5. vendored Apprise import가 Flask 기동 시간·다른 기능에 영향 없음 (지연 import) (Task 2)

---

### Task 1: Apprise 벤더링

**Files:** Create `suh-ai-server/flask/vendor/__init__.py`, `suh-ai-server/flask/vendor/apprise/**` (원본 복사), `vendor/apprise/LICENSE`, `vendor/apprise/VENDORED.md`; Modify `requirements.txt`; Test `test/test_vendored_apprise.py`

**Interfaces:** Produces `from vendor.apprise import Apprise, NotifyFormat` 사용 가능

- [ ] **Step 1: 원본 그대로 복사 + VENDORED.md + LICENSE > 커밋 1** (`docs` 아님, `chore` 타입: 메시지 설명 "Apprise v2.2.0 원본 복사")
- [ ] **Step 2: 실패 테스트** — `test_vendored_apprise_imports`: `from vendor.apprise import Apprise`; `test_vendored_apprise_parses_discord_url`: `Apprise.instantiate("discord://1234/abcd")`가 None 아님; `test_vendored_apprise_rejects_garbage`: `Apprise.instantiate("nope://x")` None; `test_vendored_apprise_json_notify` : 로컬 가짜 HTTP 서버(또는 `requests` 패치)로 `json://` 발송 1건 확인
- [ ] **Step 3: 수정** — 절대 import를 상대 import로, 누락 의존성 requirements 고정 추가, VENDORED.md "고친 목록"에 기록
- [ ] **Step 4: 통과 확인** (전체 테스트, uv 명령) > **커밋 2**

### Task 2: 받을 곳 저장·암호화·발송

**Files:** Create `service/secret_cipher.py`(범용, 기존 `claude_login_secret_cipher` 내용 이동 + 기존 import는 새 모듈 사용), `service/control_tower/destination_store.py`(믹스인), `service/control_tower/destination_delivery.py`; Modify `store_schema.py`, `store.py`, `event_dispatcher.py`, `config/control_tower_config.py`; Test `test/test_control_tower_destinations.py`

**Interfaces:**
- 테이블 `project_event_destination(destination_id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, kind TEXT NOT NULL, label TEXT NOT NULL, url_encrypted BLOB NOT NULL, encryption_scheme TEXT NOT NULL, url_hint TEXT NOT NULL, is_enabled INTEGER NOT NULL, last_result TEXT, last_sent_at TEXT, created_at TEXT NOT NULL)` (`url_hint` = 수단 + 끝 4자리)
- `DestinationStoreMixin`: `insert_destination(...) -> int`, `delete_destination(destination_id) -> bool`, `set_destination_enabled(destination_id, is_enabled) -> bool`, `list_destinations(project_id: str | None = None) -> list[Destination]`, `list_enabled_destinations(project_id, kind) -> list[Destination]`, `record_destination_result(destination_id, result: str, now)`
- `Destination` frozen dataclass (url 원문 없음)
- `destination_delivery.encrypt_destination_url(url, environ) -> (bytes, scheme)`, `describe_url_hint(url) -> str`, `is_destination_url_supported(url) -> bool` (vendored Apprise instantiate)
- `destination_delivery.DestinationDeliverer(store, run_in_background)` 에 `deliver(notification) -> None` (프로젝트 scope만, 채널 종류 계산은 dispatcher와 같은 함수 공유, 백그라운드 실행, 결과 기록)
- `EventDispatcher(..., destination_deliverer=None)`; `dispatch`는 기본 발송 후 `destination_deliverer.deliver(notification)` 호출(예외 삼킴). bootstrap에서 연결
- 메시지 형식: 제목 = notification.title, 본문 = body + 빈 줄 + `이름: 값` 줄들 + 링크(있으면). `NotifyFormat.MARKDOWN` 아님 TEXT
- [ ] **Step 1: 실패 테스트** — 암호화 왕복(같은 비밀값), 다른 비밀값이면 복호화 실패 / 저장 행에 URL 원문 없음 / dispatch: 프로젝트 알림 > 등록된 2곳 중 활성 1곳만 발송, 비활성·다른 kind·다른 프로젝트 제외 / 전역 알림 발송 없음 / 받을 곳 예외 > 기본 발송 결과 True 유지, `last_result` 기록에 URL 없음 / 비밀값 없음 > 발송 생략 + 경고 간격 제한 / 백그라운드 실행 함수 주입으로 동기 검증
- [ ] **Step 2~4**: 실패 확인 > 구현 > 전체 테스트 통과 > 커밋

### Task 3: 관리 API·화면·문서

**Files:** Create `router/control_tower_destination_api.py`, `static/js/control-manage-destinations.js`; Modify `router/control_tower_router.py`, `service/audit_service.py`, `static/js/audit.js`, `service/control_tower/manage_view.py`, 템플릿·`control-manage.js` 연결, `docs/control-tower/events/README.md`; Test `test/test_control_tower_destination_api.py`

**Interfaces:**
- `POST /control/projects/<project_id>/destinations` body `{kind, label, url}` > 201 `{destination_id, kind, label, url_hint, is_enabled}`; 400 invalid(fields: kind/label/url, URL 해석 불가 포함); 404 unknown_project; 409 secret_not_configured; 503
- `PATCH /control/destinations/<id>` `{is_enabled}` > 200; `DELETE /control/destinations/<id>` > 204; `POST /control/destinations/<id>/test` > 200 `{is_sent}` (고정 문구 1건, 동기 실행 허용, 타임아웃 상수)
- kind 허용 = 기본 5종 ∪ 그 프로젝트 사용자 정의 종류 (1단계 단일 원본 재사용)
- 감사 액션 4개 (`CONTROL_DESTINATION_CREATE/UPDATE/DELETE/TEST`), 상세에 URL 없음 (project_id, kind, label, url_hint만)
- manage 응답: 프로젝트마다 `destinations` 목록(url_hint만)
- 화면: 프로젝트 영역 "추가로 받을 곳" — 표(종류, 이름, 수단, 사용, 최근 결과, 테스트·삭제) + 추가 폼(종류 선택, 이름, URL, 예시 안내: `discord://웹훅ID/웹훅토큰`, `slack://...`, `tgram://...`, `mailto://...`). 비밀값 없으면 비활성 + 안내
- README: "팀 Discord·슬랙으로도 받기" 절 추가 + **2단계 문서 정정**: `CONTROL_TOWER_SECRET`은 배포 때 GitHub Secret `FLASK_ENV_FILE`로 서버 `.env`가 다시 만들어지므로 그 Secret에 추가(서버 `.env` 직접 수정은 다음 배포 때 덮어써짐). 같은 값이 받을 곳 URL 암호화 키이기도 함을 명시
- [ ] **Step 1: 실패 테스트** — 위 응답 계약 + 감사·manage·caplog에 URL 원문 없음 + 테스트 발송이 가짜 Apprise로 1건 + 해석 불가 URL 400
- [ ] **Step 2~4**: 실패 확인 > 구현 > 전체 테스트 + `node --check` > 커밋
