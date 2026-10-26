# Claude 로그인 6자리 코드 대시보드 표시 — 설계

- 이슈: https://github.com/Cassiiopeia/suh-project-control/issues/142
- 대상: `suh-ai-server/flask` (Windows 서버 상시 가동, waitress)
- 작성일: 2026-10-26

## 1. 의도

Claude 계정(chan4760@gmail.com) 로그인은 이메일 매직링크 방식이다. 지금은 로그인할 때마다
Gmail 접속 > Anthropic 메일 찾기 > "로그인" 버튼 > 열린 페이지의 6자리 코드 확인 > 로그인 화면에 입력을 손으로 한다.
이것을 관리 대시보드 한 화면에서 끝낸다. 사용자는 Gmail 에 들어가지 않고, 대시보드에 뜬 6자리 코드를 로그인 화면에 붙여넣기만 한다.

사용자가 강조한 것:
- 알아서 트리거되고 자동으로 진행될 것
- 진행 과정이 웹 화면에 잘 보일 것
- 감사로그에 "누가(IP 등) 코드를 받아 갔는지"가 잘 남고 잘 보일 것
- 범위는 **6자리 코드까지** (Claude Code 최종 코드 발급·CLI 입력은 하지 않음)

## 2. 확인된 사실 (2026-10-26 Mac 시험)

- 로그인 시작: `claude auth login` 또는 claude.ai 로그인 화면에서 "이메일로 계속하기" > 메일 발송
- 메일: 발신 `*@mail.anthropic.com`, 제목 `Claude의 보안 링크가 도착했습니다 | YYYY-MM-DD HH:MM:SS`,
  HTML 본문에 `https://claude.ai/magic-link#<토큰>` 직접 포함, 유효 10분
- 매직링크를 **로그인을 시작한 곳과 다른 브라우저**(헤드리스 Chromium, 새 프로필)로 열면
  "인증 코드를 사용하여 계속하기" 화면에 6자리 숫자 표시. Cloudflare 차단 없음, 메일 도착 후 약 25초
- 그 6자리 코드를 원래 로그인 화면의 "인증 코드" 입력칸에 넣으면 로그인 진행 > 승인 > Claude Code 로그인 성공까지 확인
- Gmail 은 IMAP + **앱 비밀번호**로 읽는다 (일반 비밀번호 IMAP 차단). 앱 비밀번호는 생성 완료
  (이름 `suh-control claude login`, 값은 사용자 보관)
- 매직링크는 1회용: 서버가 열면 소모되어 사람이 메일에서 다시 누를 수 없다
- 미확인: Windows 서버 IP 에서도 Cloudflare 차단 없이 같은 화면이 나오는지

## 3. 목표 / 비목표 / 실패 기준

목표
- 대시보드 새 메뉴 "Claude 로그인" 화면
- 화면을 열면 서버가 자동으로 메일 대기 시작 (버튼 없이 트리거). 수동 "다시 기다리기" 버튼도 제공
- 단계별 진행 표시: 메일 대기 > 메일 수신 > 링크 열기 > 코드 획득 (또는 실패 단계와 사유)
- 6자리 코드를 크게 표시 + 복사 버튼 + 남은 유효시간
- 감사로그: 코드 요청·발급·열람을 IP·User-Agent 와 함께 기록, 기존 감사로그 화면에서 필터·조회

비목표
- 서버 자신의 Claude Code 를 자동 로그인 (승인 클릭, 최종 코드 CLI 입력) — 시험으로 가능함은 확인했으나 이번 범위 아님
- 여러 Gmail 계정 지원 (설정은 주소 하나)
- 6자리 코드 이력 보관·재조회

실패로 보는 것 (동작해도)
- 앱 비밀번호, 매직링크 토큰이 로그·감사로그·응답·화면에 노출
- 메일을 읽음 처리·삭제·이동 등 메일함 상태 변경
- 관리자 인증 없이 코드가 보이는 경로
- 감사 DB 장애가 코드 조회를 막음 (기존 fail-open 정책 위반)

## 4. 동작 설계

### 4.1 흐름
```
사용자: 어디서든 Claude 로그인 시작 > 이메일 입력 (메일 발송)
사용자: 대시보드 "Claude 로그인" 화면 열기
  └ 화면이 POST /claude-login/code/request 호출 (자동 트리거)
서버 백그라운드 작업 (1개만 동시 실행):
  1) waiting   Gmail IMAP 폴링 (5초 간격, 최대 10분)
  2) received  새 Anthropic 메일 발견 > 매직링크 추출
  3) opening   헤드리스 Chromium 으로 링크 열기
  4) issued    화면에서 6자리 코드 추출 > 상태에 저장
  실패: timeout(10분 무메일) / code_not_found(화면에 코드 없음, 캡처 저장) / mail_error / browser_error
화면: GET /claude-login/code/status 를 2초 간격 폴링 > 단계 표시, 코드 표시
```

### 4.2 "새 메일" 판정
- 대상: INBOX, `FROM mail.anthropic.com`, 메일 `Date` 가 **작업 시작 2분 전 이후** (화면을 늦게 연 경우 포함), 그리고 수신 후 10분 이내(링크 유효)
- 이미 처리한 메일(Message-ID)은 다시 열지 않는다 (서버 메모리에 최근 목록 보관). 1회용 링크 소모 방지
- 메일함은 읽기 전용(`select readonly`, `BODY.PEEK`)으로만 접근

### 4.3 동시 실행·재요청
- 진행 중이면 request 는 새 작업을 만들지 않고 현재 작업 상태를 돌려준다 (팰월드 업데이트 `start_update` 와 같은 패턴)
- 코드 발급 후에는 상태를 유지하다가 메일 수신 시각 기준 10분이 지나면 코드를 상태에서 지운다
- "다시 기다리기" 버튼: 완료·실패 상태에서 새 작업 시작

### 4.4 화면 (`/admin/claude-login`)
- 기존 admin 레이아웃(base.html, daisyUI) + 사이드 메뉴 항목 추가
- 단계 표시: 대기 > 수신 > 링크 열기 > 코드 획득, 단계별 시각과 경과 초
- 코드 카드 (화면의 주인공, 사용자 요청 3가지): 6자리 큰 글씨 + **복사 버튼** + **메일이 몇 시에 왔는지**(예: "오전 9:34:14 수신 · 2분 전")
  - 보조: 남은 유효시간 카운트다운, 대상 계정
- 실패 시: 실패 단계·사유, code_not_found 면 서버가 저장한 캡처 이미지 표시
- 안내 문구: "로그인 화면에서 이메일 입력 후 기다리세요" 
- 하단: 이 기능의 최근 감사로그 10건 (기존 감사 조회 API 를 카테고리 필터로 호출)
- 프론트 요청은 반드시 `window.apiFetch` 사용 (flask/CLAUDE.md 규칙)

### 4.5 감사로그
- 새 카테고리 `CLAUDE_LOGIN`, 새 행위 3개
  - `CLAUDE_CODE_REQUEST`: 대기 시작 (요청자 IP·UA, 자동/수동 트리거)
  - `CLAUDE_CODE_ISSUED`: 코드 획득 또는 실패 (성공 여부, 실패 단계·사유, 메일 수신 시각, 소요 초, 대상 계정). 백그라운드 스레드라 `audit_service.record()` 직접 호출, 요청자 IP 를 행위자로 기록
  - `CLAUDE_CODE_VIEW`: **코드가 특정 클라이언트에 처음 전달된 순간** 1회 기록 (작업 ID + 클라이언트 IP 기준 중복 제거). "누가 받아 갔는지"의 근거
- 6자리 코드 원문은 감사로그에 남기지 않는다 (작업 ID 로 연결)
- 추가 절차는 flask/CLAUDE.md "새 카테고리/행위 추가 절차" 그대로 (enum, `audit.js` 라벨·카테고리 메타, `audit.html` 셀렉트)

### 4.6 API (관리자 API 키 필수, 기존 방식)
| 메서드 | 경로 | 내용 | 감사 |
|---|---|---|---|
| POST | `/claude-login/code/request` | 대기 시작 (진행 중이면 현재 상태) | REQUEST (새 작업일 때만) |
| GET | `/claude-login/code/status` | 단계·시각·코드(발급 시)·실패 사유 | 코드 포함 응답 시 VIEW (IP별 1회) |
| GET | `/claude-login/code/screenshot` | 실패 캡처 이미지 | 없음 |

### 4.7 설정·비밀값
- 환경변수 (서버 `.env`, python-dotenv 로 로드 중)
  - `CLAUDE_LOGIN_GMAIL_ADDRESS` (예: chan4760@gmail.com)
  - `CLAUDE_LOGIN_GMAIL_APP_PASSWORD` (16자리)
- 서버 `flask/.env` 는 배포 때마다 GitHub Secret `FLASK_ENV_FILE` 내용으로 새로 만들어진다
  (`.github/workflows/SUH-AI-PROJECT-CONTROL.yaml` "Flask .env 생성" 단계). 서버 파일 직접 수정은 다음 배포에 지워짐
- **[사용자 결정]** 기존 Secret `FLASK_ENV_FILE` 을 갱신한다 (.env 파일 통째로 한 번에 올리는 방식 유지, 워크플로 변경 없음)
  - 원본: Windows 서버 `C:\AI\suh-ai-server\flask\.env` (현재 키 3개: `AUDIT_DATABASE_URL`, `SUNSHINE_WEB_USER`, `SUNSHINE_WEB_PASSWORD`).
    시놀로지 `/volume1/projects/suh-project` 에는 .env 사본 없음 (2026-10-26 확인)
  - 절차: 서버 .env 읽기(`pro-ssh`, 값 출력 금지) > 위 2줄 추가 > `/pro-github secrets set` 으로 `FLASK_ENV_FILE` 갱신 > 다음 배포에서 서버 .env 재생성 확인
  - 진행: 구현 단계에서 Claude (앱 비밀번호 값은 사용자 Mac `~/Downloads/claude-magic-link-code/gmail_app_password.txt`)
- 미설정이면 화면에 "설정 필요" 표시, 작업 시작 거부 (400)
- 상수(폴링 간격 5초, 대기 10분, 시작 전 허용 2분, 링크 유효 10분)는 `config/` 에 이름 있는 상수로

### 4.8 브라우저
- Python Playwright + Chromium 헤드리스, 작업마다 새 컨텍스트(쿠키 없음), locale ko-KR
- 페이지 로드 후 최대 15초 동안 본문에서 6자리 숫자 탐색 ("인증 코드" 문구 근처 우선)
- `requirements.txt` 에 playwright 추가, 배포 스크립트(`scripts/deploy-flask.ps1`)에 `python -m playwright install chromium` 추가
- **[설계자 결정]** NSSM 서비스 계정과 배포 실행 계정이 달라도 브라우저를 찾도록 `PLAYWRIGHT_BROWSERS_PATH` 를 고정 경로로 지정 (설치·실행 양쪽 동일)

### 4.9 인증·식별 (코드 확인 결과)
- nginx 상 `/api/flask/admin` 화면은 키 없이 열리고, `/api/flask/` API 는 `X-API-Key` 필요 > 새 API 3개는 추가 작업 없이 보호됨
- API 키를 함께 쓰므로 "누가"는 IP + User-Agent 로 식별 (감사 데코레이터가 자동 수집)
- POST request: `@audited(CLAUDE_LOGIN)` + 새 작업일 때만 `set_audit_action` / 백그라운드: `audit_service.record()` 직접 호출
- 화면 하단 최근 기록: 기존 `/audit/logs?category=CLAUDE_LOGIN`

## 5. 코드 위치 (기존 구조 따름)
- `service/claude_login_code_service.py` — 백그라운드 작업·상태 (palworld_updater 패턴)
- `service/` 또는 `util/` 아래 Gmail 조회, 매직링크 브라우저 열기 분리 (각각 단위 테스트 가능하게)
- `router/claude_login_router.py` — API 3개
- `router/admin_router.py` — `/admin/claude-login` 화면
- `templates/admin/claude_login.html`, `static/js/claude-login.js`
- `config/claude_login_config.py` — 상수·환경변수
- 테스트: `test/` 에 메일 파싱(샘플 HTML), 새 메일 판정, 상태 전이, VIEW 중복 제거, 감사 기록 호출

## 6. 빌더에게 맡기는 것
- 단계 표시 UI 세부 모양 (기존 팰월드 업데이트 진행 표시와 비슷하게)
- Gmail 조회와 브라우저 부분의 모듈 경계
- Windows 서버 첫 배포 시 Cloudflare 차단 여부 실측 (막히면 이 설계의 4.8 재검토 필요, 사용자에게 보고)
