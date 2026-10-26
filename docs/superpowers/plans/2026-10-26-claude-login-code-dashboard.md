# Claude 로그인 6자리 코드 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리 대시보드 `/admin/claude-login` 화면을 열면 서버가 Gmail 의 Claude 매직링크 메일을 기다렸다가 링크를 헤드리스 브라우저로 열어 6자리 코드를 읽고, 코드·복사 버튼·메일 수신 시각을 보여주며 요청·발급·열람을 감사로그에 남긴다.

**Architecture:** palworld_updater 와 같은 "모듈 상태 + 백그라운드 스레드 + 상태 폴링" 구조. Gmail 조회(IMAP)와 브라우저 코드 읽기(Playwright)는 각각 독립 client 모듈로 두고, 서비스가 둘을 주입받아 상태 전이를 관리한다. 라우터는 서비스 호출과 감사 기록만 한다.

**Tech Stack:** Flask 3, waitress, imaplib(표준), Playwright(Python, Chromium headless), psycopg2 감사로그, daisyUI 템플릿

**Spec:** `docs/superpowers/specs/2026-10-26-claude-login-code-dashboard-design.md` (이슈 #142)

## Global Constraints

- 작업 위치 `suh-ai-server/flask`, 테스트 `python3 -m pytest test/ -q`
- 환경변수 `CLAUDE_LOGIN_GMAIL_ADDRESS`, `CLAUDE_LOGIN_GMAIL_APP_PASSWORD` (미설정 시 작업 시작 400 + 화면 "설정 필요")
- 상수: 폴링 5초, 대기 최대 600초, 작업 시작 전 허용 120초, 링크 유효 600초, 페이지 코드 탐색 최대 15초
- IMAP: `imap.gmail.com`, `INBOX` readonly, `BODY.PEEK`, `FROM mail.anthropic.com` — 메일함 상태 변경 금지
- 매직링크 정규식 `https://claude\.ai/magic-link#[^"]+`, 6자리 코드 `\d{6}`
- 앱 비밀번호·매직링크 토큰·6자리 코드는 로그·감사로그에 남기지 않음 (코드는 status API 응답에만)
- 감사: 카테고리 `CLAUDE_LOGIN`, 행위 `CLAUDE_CODE_REQUEST` / `CLAUDE_CODE_ISSUED` / `CLAUDE_CODE_VIEW`, fail-open 유지
- 프론트 요청은 `window.apiFetch` 만 사용, 새 Tailwind 클래스 쓰면 `frontend/` 에서 `npm run build` 후 `static/css/app.css` 함께 커밋
- `PLAYWRIGHT_BROWSERS_PATH` 는 `C:\AI\playwright-browsers` 로 고정 (설치·실행 동일)
- 주석·네이밍은 사용자 전역 규칙(한국어 한 줄 요약, boolean is/has, 약어 금지), 로그 문구는 영어 `[claude login] ...`
- 커밋은 `/pro-commit`, 브랜치 `20261026_#142_기능추가_관리자_Claude_로그인_인증코드_대시보드_자동_표시` (develop 기준 worktree)

## Review Focus

1. 화면을 늦게 연 경우(메일이 작업 시작 전 2분 이내 도착) — 그 메일을 잡아야 함 → Task 1 `test_selects_mail_received_shortly_before_start`
2. 이미 열어 소모한 메일이 다시 잡힘 — 같은 Message-ID 재처리 금지 → Task 1 `test_skips_already_processed_message_id`
3. 화면 두 개(두 관리자)가 동시에 열림 — 작업 1개만, 둘 다 같은 상태, VIEW 는 IP별 1회 → Task 3 `test_second_request_while_running_returns_same_job`, `test_view_recorded_once_per_ip`
4. 10분 지난 코드가 계속 보임 — 메일 수신 + 600초 후 코드 제거 → Task 3 `test_code_hidden_after_link_expiry`
5. Gmail 인증 실패/네트워크 오류 — 스레드가 죽지 않고 `failed`/`mail_error` 로 표시 → Task 3 `test_mail_error_sets_failed_state`

---

## File Structure

| 파일 | 책임 |
|---|---|
| `config/claude_login_config.py` (new) | 상수, 환경변수 읽기 |
| `service/claude_login_mail_client.py` (new) | IMAP 조회 > 새 매직링크 메일 1건 |
| `service/claude_login_browser_client.py` (new) | 매직링크 > 6자리 코드 (+실패 캡처) |
| `service/claude_login_code_service.py` (new) | 작업 상태·스레드·만료·감사 기록·VIEW 중복 제거 |
| `service/audit_service.py` (mod) | enum 추가 |
| `router/claude_login_router.py` (new) | API 3개 |
| `app.py` (mod) | 블루프린트 등록 |
| `router/admin_router.py`, `templates/admin/claude_login.html` (new), `templates/admin/base.html`, `static/js/claude-login.js` (new) | 화면 |
| `static/js/audit.js`, `templates/admin/audit.html` | 감사 라벨·필터 |
| `requirements.txt`, `../scripts/deploy-flask.ps1` | 의존성·Chromium 설치 |

---

### Task 1: 설정 + Gmail 매직링크 조회

**Files:**
- Create: `config/claude_login_config.py`, `service/claude_login_mail_client.py`
- Test: `test/test_claude_login_mail_client.py`

**Interfaces:**
- Produces:
  - `config.claude_login_config`: `POLL_INTERVAL_SECONDS=5`, `MAIL_WAIT_TIMEOUT_SECONDS=600`, `MAIL_ACCEPT_BEFORE_START_SECONDS=120`, `MAGIC_LINK_VALID_SECONDS=600`, `CODE_SEARCH_TIMEOUT_SECONDS=15`, `PLAYWRIGHT_BROWSERS_DIRECTORY=r'C:\AI\playwright-browsers'`, `get_gmail_address() -> str | None`, `get_gmail_app_password() -> str | None`, `is_configured() -> bool`
  - `@dataclass MagicLinkMail(message_id: str, received_at: datetime, magic_link: str)`
  - `extract_magic_link(html: str) -> str | None`
  - `find_new_magic_link_mail(address, app_password, accept_after: datetime, processed_message_ids: set[str], imap_factory=imaplib.IMAP4_SSL) -> MagicLinkMail | None` — 최신 3건 중 `received_at >= accept_after` 이고 미처리인 가장 최신 1건. `MailClientError` 로 IMAP 예외 감쌈

- [ ] **Step 1: Write the failing tests** — 샘플 HTML 은 실제 메일 구조(추적 링크 여러 개 + `href="https://claude.ai/magic-link#abc:ZGVm"`)
  - `test_extract_magic_link_ignores_tracking_links` → `== "https://claude.ai/magic-link#abc:ZGVm"`
  - `test_extract_magic_link_returns_none_without_link`
  - `test_selects_mail_received_shortly_before_start` — 메일 Date = accept_after + 10초 → 반환 (accept_after 는 호출부가 시작시각-120초로 넘김)
  - `test_ignores_mail_older_than_accept_after`
  - `test_skips_already_processed_message_id`
  - `test_uses_readonly_select_and_peek` — fake IMAP 이 `select("INBOX", readonly=True)` 와 `(BODY.PEEK[])` 로 호출됐는지
  - `test_imap_login_failure_raises_mail_client_error`
- [ ] **Step 2:** `python3 -m pytest test/test_claude_login_mail_client.py -q` → FAIL (모듈 없음)
- [ ] **Step 3:** 구현. 검색은 `search(None, "FROM", "mail.anthropic.com", "SINCE", <accept_after 날짜 %d-%b-%Y>)`, Message-ID 헤더 없으면 IMAP id 사용
- [ ] **Step 4:** 같은 명령 → PASS
- [ ] **Step 5:** `/pro-commit` (feat)

### Task 2: 브라우저로 6자리 코드 읽기

**Files:**
- Create: `service/claude_login_browser_client.py`
- Test: `test/test_claude_login_browser_client.py`

**Interfaces:**
- Consumes: `CODE_SEARCH_TIMEOUT_SECONDS`, `PLAYWRIGHT_BROWSERS_DIRECTORY`
- Produces:
  - `extract_login_code(page_text: str) -> str | None` — "인증 코드" 문구 이후 첫 `\d{6}` 우선, 없으면 본문 첫 `\d{6}`
  - `read_login_code(magic_link: str, screenshot_path: str) -> str` — 새 컨텍스트(locale ko-KR) headless, 코드 못 찾으면 캡처 저장 후 `LoginCodeNotFoundError`, 브라우저 예외는 `BrowserClientError`. 모듈 import 시 `os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', ...)` (Windows 에서만, `os.name == 'nt'`)
- [ ] **Step 1: Write the failing tests** (Playwright 실제 실행 없음)
  - `test_extract_code_from_real_page_text` — 입력 `"인증 코드를 사용하여 계속하기\n처음 로그인을 시도한 곳에 이 인증 코드를 입력하세요\n027696\n코드 복사"` → `"027696"`
  - `test_extract_code_prefers_number_after_label` — 앞에 다른 6자리(`"2026-10 123456 ... 인증 코드 ... 654321"`) → `"654321"`
  - `test_extract_code_none_when_absent`
- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현 (`read_login_code` 는 `sync_playwright` 로 goto > 0.5초 간격 `inner_text("body")` 재시도, 최대 15초)
- [ ] **Step 4:** pytest → PASS. 추가로 로컬 Mac 에서 `pip install playwright && python -m playwright install chromium` 후 실제 메일 1건으로 `read_login_code` 수동 실행해 코드 반환 확인 (사용자에게 로그인 메일 발송 요청)
- [ ] **Step 5:** `requirements.txt` 에 `playwright==1.49.1` 추가 (fold), `/pro-commit`

### Task 3: 코드 작업 서비스 (상태·스레드·만료·감사)

**Files:**
- Create: `service/claude_login_code_service.py`
- Modify: `service/audit_service.py` (enum: `AuditCategory.CLAUDE_LOGIN`, `AuditAction.CLAUDE_CODE_REQUEST/ISSUED/VIEW`)
- Test: `test/test_claude_login_code_service.py`

**Interfaces:**
- Consumes: Task 1 `find_new_magic_link_mail`, `MagicLinkMail`, `MailClientError`; Task 2 `read_login_code`, `LoginCodeNotFoundError`, `BrowserClientError`
- Produces:
  - 상태 dict (status API 응답 그대로): `job_id: str`, `status: 'idle'|'running'|'issued'|'failed'|'expired'`, `step: 'waiting'|'received'|'opening'|'issued'`, `trigger: 'auto'|'manual'`, `started_at`, `step_times: {step: iso}`, `mail_received_at: iso|None`, `expires_at: iso|None`, `code: str|None`, `account: str`, `failure_reason: 'timeout'|'code_not_found'|'mail_error'|'browser_error'|None`, `has_screenshot: bool`, `is_configured: bool`
  - `start_request(trigger: str, client: dict, *, run_in_thread=True) -> tuple[dict, bool]` — (상태, 새 작업 여부). 진행 중이면 기존 상태 + False. 미설정이면 `NotConfiguredError`
  - `get_state(now: datetime | None = None) -> dict` — `expires_at` 지났으면 code 제거·status `expired`
  - `should_record_view(job_id: str, client_ip: str) -> bool` — 첫 호출만 True
  - `SCREENSHOT_PATH` (logs/claude_login_failure.png)
  - 테스트용 주입: `_run_job(job_id, client)` 를 동기 호출 가능, mail/browser 함수는 모듈 속성으로 patch
- 감사: REQUEST 는 라우터(Task 4)가 기록. 서비스는 작업 종료 시 `CLAUDE_CODE_ISSUED` 만 `audit_service.record(..., client['actor_ip'], detail, client_ip=..., user_agent=..., success=...)` (success 성공/실패, detail: job_id, failure_reason, mail_received_at, elapsed_seconds, account — 코드 제외). 처리한 Message-ID 는 실패해도 processed 에 추가
- [ ] **Step 1: Write the failing tests** (mail/browser/audit 를 patch, `run_in_thread=False`)
  - `test_issued_flow_sets_code_and_mail_time` — status `issued`, code `"027696"`, `mail_received_at` 채워짐, `expires_at == received + 600s`
  - `test_second_request_while_running_returns_same_job` — 두 번째 호출 False, 같은 job_id
  - `test_accept_after_is_start_minus_120_seconds` — mail client 에 넘긴 accept_after 확인
  - `test_timeout_sets_failed_timeout` — 시계 patch 로 600초 경과, mail None
  - `test_mail_error_sets_failed_state` — `MailClientError` → `failed`/`mail_error`, ISSUED success False
  - `test_code_not_found_sets_screenshot_flag`
  - `test_code_hidden_after_link_expiry` — `get_state(now=received+601s)` → code None, status `expired`
  - `test_view_recorded_once_per_ip` — 같은 (job, ip) 두 번째 False, 다른 ip True
  - `test_issued_audit_detail_excludes_code` — record 호출 인자에 `"027696"` 미포함
  - `test_start_without_config_raises_not_configured`
- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현 (모듈 `_lock`, `_state`, `_processed_message_ids`(최근 50), `_viewed` set; 로그 `[claude login] ...` 단계 전이마다)
- [ ] **Step 4:** pytest 전체 `python3 -m pytest test/ -q` → PASS
- [ ] **Step 5:** `/pro-commit`

### Task 4: API 라우터

**Files:**
- Create: `router/claude_login_router.py`
- Modify: `app.py` (import + `register_blueprint(claude_login_bp)`)
- Test: `test/test_claude_login_router.py`

**Interfaces:**
- Consumes: Task 3 `start_request`, `get_state`, `should_record_view`, `NotConfiguredError`, `SCREENSHOT_PATH`; `util.audit_helper.audited`, `set_audit_action`, `set_audit_detail`, `client_info`
- Produces:
  - `POST /claude-login/code/request` body `{"trigger": "auto"|"manual"}` → 200 상태 / 400 `{"error":"not_configured"}`. `@audited(AuditCategory.CLAUDE_LOGIN)`, 새 작업일 때만 `set_audit_action(CLAUDE_CODE_REQUEST)` + `set_audit_detail({'job_id','trigger','account'})`
  - `GET /claude-login/code/status` → 상태; `code` 가 있고 `should_record_view` True 면 `audit_service.record(..., CLAUDE_CODE_VIEW, ..., {'job_id', 'mail_received_at'})`
  - `GET /claude-login/code/screenshot` → png 또는 404
- [ ] **Step 1: Write the failing tests**
  - `test_request_returns_state`, `test_request_not_configured_returns_400`
  - `test_request_records_audit_only_for_new_job` (audit_service.record patch, 기존 작업이면 0회)
  - `test_status_records_view_once_when_code_present`, `test_status_without_code_records_no_view`
  - `test_screenshot_404_when_missing`
- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현
- [ ] **Step 4:** pytest 전체 → PASS
- [ ] **Step 5:** `/pro-commit`

### Task 5: 관리 화면 + 감사 라벨

**Files:**
- Modify: `router/admin_router.py` (`/admin/claude-login` → `admin/claude_login.html`, root='..', active='claude-login'), `templates/admin/base.html` (메뉴 "Claude 로그인", lucide `key-round`, 감사로그 위), `static/js/audit.js` (CATEGORY_META `CLAUDE_LOGIN: {label:'Claude 로그인', badge:...}`, ACTION_LABELS 3개: `코드 요청` / `코드 발급` / `코드 열람`, ACTIONS_BY_CATEGORY), `templates/admin/audit.html` (`<option value="CLAUDE_LOGIN">Claude 로그인</option>`)
- Create: `templates/admin/claude_login.html`, `static/js/claude-login.js`
- Test: `test/test_admin_router.py` (추가)

**화면 요구 (스펙 4.4):**
- 진입 시 `apiFetch('claude-login/code/request', POST {trigger:'auto'})`, 이후 2초 간격 status 폴링, `issued/failed/expired` 면 폴링 중단
- 단계 표시 4개(메일 대기 > 메일 수신 > 링크 열기 > 코드 획득) + 각 단계 시각
- 코드 카드: 6자리 큰 글씨, **복사 버튼**(navigator.clipboard, 실패 시 텍스트 선택), **"오전 9:34:14 수신 · 2분 전"**, 남은 유효시간 카운트다운, 계정
- 실패: 사유 한국어(시간 초과 / 화면에서 코드 못 찾음 / 메일 접속 오류 / 브라우저 오류), code_not_found 면 screenshot 이미지
- "다시 기다리기" 버튼(trigger manual), 미설정이면 안내만
- 하단 최근 감사 10건: 기존 감사 조회 API `audit/logs?category=CLAUDE_LOGIN` 재사용 (응답 형식은 `audit.js` 참고)
- 안내 문구: "Claude 로그인 화면에서 이메일을 입력한 뒤 이 화면에서 기다리세요"
- [ ] **Step 1: Write the failing tests**
  - `test_claude_login_page_renders` — 200, `'Claude 로그인'`, `'claude-login.js'` 포함, EMOJI_RE 미검출
  - `test_menu_has_claude_login_link` — `/admin` 응답에 `admin/claude-login` 링크
- [ ] **Step 2:** pytest → FAIL
- [ ] **Step 3:** 구현 → `cd frontend && npm run build` (새 클래스 반영)
- [ ] **Step 4:** pytest 전체 → PASS. 로컬 `python3 run.py` 띄워 `/pro-launch` 로 화면 캡처 (라이트·다크, 설정 미설정 상태 / 서비스 patch 한 issued 상태는 `web route` 로 status 응답 모킹)
- [ ] **Step 5:** `/pro-commit`

### Task 6: 배포 준비 + Secret + 서버 실측

**Files:**
- Modify: `../scripts/deploy-flask.ps1` — pip install 다음에 `$env:PLAYWRIGHT_BROWSERS_PATH = 'C:\AI\playwright-browsers'` 후 `& $pythonExe -m playwright install chromium` (실패 시 WARN 만, 배포 중단 안 함)

- [ ] **Step 1:** ps1 수정, `/pro-commit`
- [ ] **Step 2:** Secret 갱신 — `/pro-ssh`(suh-ai-windows)로 `C:\AI\suh-ai-server\flask\.env` 를 로컬 임시파일(권한 600, scratchpad)로 복사 > `CLAUDE_LOGIN_GMAIL_ADDRESS=chan4760@gmail.com`, `CLAUDE_LOGIN_GMAIL_APP_PASSWORD=<~/Downloads/claude-magic-link-code/gmail_app_password.txt 값>` 추가 > `/pro-github secrets set` 으로 `FLASK_ENV_FILE` 갱신 > 임시파일 삭제. 값은 출력하지 않음, 키 이름 목록으로만 확인 (5개)
- [ ] **Step 3:** push · develop 반영은 사용자 확인 후 (전역 규칙). 배포는 `/pro-changelog-deploy`, 사용자 요청 시에만
- [ ] **Step 4:** 배포 후 실측: 서버 .env 키 5개 확인(값 미출력), 서비스 로그 `[claude login]`, 사용자에게 로그인 메일 발송 요청 > `https://ai.suhsaechan.kr/api/flask/admin/claude-login` 을 `/pro-launch` 로 열어 단계 진행·코드·수신 시각·복사 버튼 캡처 > 감사로그 화면에 요청·발급·열람 3건 확인. Cloudflare 차단 시 사용자 보고
- [ ] **Step 5:** `/pro-report` 로 #142 보고서, 라벨 완료
