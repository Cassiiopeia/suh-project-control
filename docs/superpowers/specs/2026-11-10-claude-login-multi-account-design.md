# Claude 로그인 코드 다중 계정 설계

## 목적
- `/admin/claude-login` 은 지금 `.env` 의 Gmail 1개만 처리 > 계정 3개 이상을 관리자 화면에서 등록·처리
- 계정 정보는 DB 에서 관리, 앱 비밀번호는 AES 로 암호화 저장 (키는 DB 밖 `.env`)
- 나중에 Windows > Mac 서버 이전 시 같은 비밀 문구만 옮기면 복호화 가능해야 함

## 목표 / 비목표
- 목표: 계정 CRUD(추가·수정·사용 토글·삭제·접속 테스트), 등록 계정 동시 대기, 계정별 코드 카드
- 비목표: Gmail 외 IMAP 제공자, OAuth 방식 Gmail 접속, 계정별 권한 분리
- 실패로 보는 것: 앱 비밀번호 평문이 DB·로그·API 응답·감사로그에 남는 것

## 결정 사항 (사용자)
- 계정 정보 저장 위치: DB (`.env` 의 `CLAUDE_LOGIN_GMAIL_*` 는 더 이상 쓰지 않음)
- 암호화: AES, 사용자가 정한 비밀 문구 기반 (DPAPI 안 씀, 플랫폼 독립)

## 결정 사항 (구현자 판단, 변경 가능)
- 화면 (사용자 선택): 시안 B — 탭 2개 "코드 받기"(계정 카드 그리드 + 최근 기록) / "계정 관리"(표 + 추가·수정 창)
  (`docs/projectops/ui-design/20261110_001_Claude_로그인_다중_계정/screens/layout.html`)
- 키 원본: `.env` `CLAUDE_LOGIN_ACCOUNT_SECRET` (비밀 문구) > PBKDF2-HMAC-SHA256 (600,000회, 행별 16바이트 salt) > 32바이트 키 > AES-256-GCM (12바이트 nonce)
- 저장 형식: `encrypted_app_password` BYTEA = `salt(16) | nonce(12) | ciphertext+tag`, `encryption_scheme` = `pbkdf2-aes256gcm-v1` (방식 교체 대비)
- 비밀 문구 미설정: 계정 등록·대기 불가 (화면 안내), 앱은 정상 기동
- 기존 `.env` 계정 자동 이전 없음 (관리자 화면에서 1회 재등록)

## 데이터
`migrations/0004__create_claude_login_account.sql`
```
claude_login_account(
  id SERIAL PK, gmail_address VARCHAR(320) UNIQUE NOT NULL, display_name VARCHAR(100) NOT NULL,
  encrypted_app_password BYTEA NOT NULL, encryption_scheme VARCHAR(40) NOT NULL,
  is_enabled BOOLEAN NOT NULL DEFAULT TRUE, last_success_at TIMESTAMPTZ, last_test_failed BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT now(), updated_at TIMESTAMPTZ DEFAULT now())
```
DB 는 감사로그와 같은 `AUDIT_DATABASE_URL`. DB 미설정·다운이면 계정 목록 조회 실패 > 화면 안내 (`db_unavailable`).

## 구성
| 파일 | 책임 |
|---|---|
| `service/claude_login_secret_cipher.py` | 비밀 문구 > 암호화·복호화 (평문은 메모리에서만) |
| `service/claude_login_account_repository.py` | 계정 테이블 CRUD (psycopg2) |
| `service/claude_login_account_service.py` | 검증(주소 형식·16자리), IMAP 접속 테스트 후 저장, 응답 형태(비밀번호 제외) |
| `service/claude_login_code_service.py` | 작업 상태를 계정 id 별로 분리, 처리 Message-ID 계정별 |
| `service/claude_login_mail_client.py` | `test_login(address, app_password)` 추가 |
| `router/claude_login_router.py` | 계정 API + 코드 API 계정 파라미터 |

## API
- `GET /claude-login/accounts` — 목록 (비밀번호 제외, `is_secret_configured`)
- `POST /claude-login/accounts` {display_name, gmail_address, app_password} — 접속 테스트 성공 시 저장 (실패 400 `imap_login_failed`)
- `PUT /claude-login/accounts/<id>` {display_name?, is_enabled?, app_password?} — 비밀번호 바꾸면 접속 테스트
- `DELETE /claude-login/accounts/<id>`
- `POST /claude-login/accounts/<id>/test` — 저장된 비밀번호로 접속 테스트
- `POST /claude-login/code/request` {trigger, account_id?} — account_id 없으면 사용 중 계정 전체
- `GET /claude-login/code/status` — `{accounts: [계정별 상태], is_secret_configured}` (코드 열람 감사는 계정·작업·IP 별 1회)
- `GET /claude-login/code/screenshot?account_id=` — 계정별 실패 캡처 `logs/claude_login_failure_<id>.png`

## 감사
- 새 action: `CLAUDE_ACCOUNT_CREATE`, `CLAUDE_ACCOUNT_UPDATE`, `CLAUDE_ACCOUNT_DELETE`, `CLAUDE_ACCOUNT_TEST`
- detail 에 `account_id`, `gmail_address` 만 (비밀번호 절대 제외). 기존 코드 감사 detail 에 `account_id` 추가

## 동시성
- 작업은 계정별 1개, 계정 간 동시 실행 (스레드 계정당 1개). 메일 폴링 5초 × 계정 수
- 같은 메일함을 두 계정으로 등록 불가 (주소 UNIQUE)

## 이전 절차 (Windows > Mac)
- `.env` 의 `CLAUDE_LOGIN_ACCOUNT_SECRET` 과 DB 를 그대로 옮기면 복호화 동작
- 비밀 문구 교체 시: 관리자 화면에서 앱 비밀번호 재입력 (재암호화 스크립트는 범위 밖)

## 테스트
- 암호화 왕복·잘못된 비밀 문구 실패·salt 행별 상이
- 계정 서비스 검증·접속 실패 시 미저장·응답에 비밀번호 없음
- 코드 서비스 계정별 독립 상태·전체 시작
- 라우터 계정 CRUD + 감사 action
