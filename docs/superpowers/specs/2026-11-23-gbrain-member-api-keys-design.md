# gbrain 팀원별 API 키 관리 설계 메모

- 작성: 2026-11-23
- 이슈: Cassiiopeia/suh-project-control#221
- 승인: 소유자 결정 (2026-11-23) — 관제소는 소유자만 쓴다, 팀원 계정·로그인 없음, 소유자가 발급해 전달, 소유자는 나중에 다시 볼 수 있어야 함, 데이터는 관제소 DB
- 앞 문서: [토큰 관리](2026-11-22-gbrain-token-management-design.md) (#207), [팀 브레인 MCP](2026-11-23-gbrain-team-brain-mcp-design.md) (#210)

## 1. 왜

- #207 토큰 카드는 gbrain 이 가진 기기 토큰 목록만 보여 주고, 원문은 발급 결과 창에서 한 번만 보인다.
- 팀 브레인을 팀원에게 나눠 주면 "누구에게 어떤 키를 줬는지", "잃어버린 키를 다시 전달"을 관리할 곳이 없다.

## 2. 표 (관제소 DB = 감사로그와 같은 `AUDIT_DATABASE_URL`)

| 표 | 열 |
|---|---|
| `gbrain_member` | `id`, `handle`(영문 소문자 id, 토큰 이름 앞자리), `display_name`, `contact`, `memo`, `is_owner`, `is_active`, `created_at`, `updated_at`, `ended_at` |
| `gbrain_member_api_key` | `id`, `member_id`, `brain_id`(personal / 팀 프로젝트 키), `gbrain_token_id`, `token_name`, `scopes`(쉼표), `encrypted_token`(BYTEA, 없으면 NULL), `encryption_scheme`, `issued_at`, `revoked_at` |

- `(brain_id, gbrain_token_id)` 유일. 마지막 사용 시각은 저장하지 않고 팀원 펼칠 때 gbrain 목록에서 실시간으로 읽는다 (원본은 gbrain).
- gbrain 이 이미 폐기했다고 알려 주면(옛 토큰 카드에서 폐기 등) 그때 `revoked_at` 을 채운다.

## 3. 스키마 변경 방식

- 이 레포 규칙대로 `suh-ai-server/flask/migrations/` 에 yoyo SQL 파일(`0005__create_gbrain_member.sql`)을 추가한다.
- 앱 기동 시 `config/db_config.apply_migrations()` 가 자동 적용한다 (실패해도 앱은 뜸, 다음 기동에 재시도).
- 같은 파일에서 소유자 팀원(`handle=owner`, `소유자`, `is_owner`)을 넣는다 (`ON CONFLICT DO NOTHING`).

## 4. 암호화

- 기존 공통 모듈 `service/secret_cipher.py` 재사용: 비밀 문구 > PBKDF2-HMAC-SHA256(600,000회, 행별 salt) > AES-256-GCM. 의존성 `cryptography` 는 이미 있음.
- 비밀 문구는 서버 환경변수 `GBRAIN_MEMBER_KEY_SECRET` 하나 (`flask/.env`, 운영은 GitHub Secret `FLASK_ENV_FILE`). DB 에는 키가 없다.
- 환경변수가 없으면 발급·다시 보기를 막고 503 `member_key_secret_missing` 을 돌려준다. 화면은 카드 위에 설정 안내를 띄운다. 목록·팀원 관리·폐기는 키가 필요 없어 그대로 된다.
- 비밀 문구를 바꾸면 옛 값은 복호화되지 않는다 (`decrypt_failed`). 그때는 키를 폐기하고 새로 발급한다.

## 5. 흐름

| 흐름 | 순서 |
|---|---|
| 발급 | 비밀 문구 확인 > 팀원 활성 확인 > 브레인 결정 > gbrain 소유자 API 로 발급(기본 읽기 전용) > 암호화 > DB 저장 > 결과 창(`claude mcp add ...` 한 줄, 팀원 안내). DB 저장이 실패하면 방금 만든 gbrain 토큰을 폐기해 고아 토큰을 남기지 않는다 |
| 다시 보기 | 관리자 키 재입력 > 요청의 `X-API-Key`(nginx 가 이미 검증한 값)와 상수 시간 비교 > 복호화 > 결과 창 재사용 > 60초 뒤 자동으로 창을 닫고 값을 비움. 성공·실패 모두 `@audited`(`GBRAIN_MEMBER_KEY_REVEAL`). 10분 안에 5번 틀리면 429 `reveal_locked` |
| 사람별 보기 | 팀원 행 펼치기 > DB 키 목록 + 그 브레인 gbrain 목록에서 상태·마지막 사용 (gbrain 실패 시 "확인 불가", 화면은 열림) |
| 키 1개 폐기 | gbrain 폐기 > DB `revoked_at` |
| 팀원 종료 | 그 사람의 살아 있는 키를 하나씩 gbrain 에서 폐기 (이미 폐기·없음은 성공으로 봄) > 모두 끝나면 키 `revoked_at` 과 팀원 `is_active=false`, `ended_at`. 하나라도 실패하면 팀원은 활성으로 두고 실패 목록을 돌려줌 (다시 누르면 남은 것만) |
| 기존 토큰 연결 | 브레인을 골라 DB 에 없는 살아 있는 gbrain 토큰 목록 > 하나를 팀원(기본 소유자)에게 연결. 원문은 gbrain 도 모르므로 "다시 보기 불가"로 표시 |

- 기존 기기 토큰 `claude-code-mac-public` 은 배포 후 소유자 행에서 "기존 토큰 연결"로 한 번 연결한다 (토큰 카드 자체는 그대로 둔다).
- 관리자 비밀번호가 따로 없는 서버라 "재확인"은 관제소 관리자 키 재입력으로 한다. 브라우저에 저장된 키를 그대로 보내는 것이 아니라 사람이 다시 입력해야 열린다.

## 6. 값 노출 금지

- 목록·팀원·키 응답에는 `encrypted_token` 도 원문도 없다. `has_stored_secret` boolean 만 있다.
- 원문은 발급·다시 보기 응답에만, `Cache-Control: no-store`.
- 로그·감사 상세에는 팀원 id·handle·브레인·토큰 id·권한만. 시험으로 고정한다.

## 7. 감사 행위 (카테고리 `GBRAIN`)

`GBRAIN_MEMBER_CREATE`, `GBRAIN_MEMBER_UPDATE`, `GBRAIN_MEMBER_END`, `GBRAIN_MEMBER_KEY_CREATE`, `GBRAIN_MEMBER_KEY_REVOKE`, `GBRAIN_MEMBER_KEY_REVEAL`, `GBRAIN_MEMBER_KEY_LINK`

## 8. 하지 않는 것

- 팀원 로그인·계정, 토큰 값 직접 지정 (gbrain 미지원)
- gbrain `--member` 연동 (소유자 HTTP API 에 member 필드가 없음, 사람 연결은 관제소 DB 가 원본)
- 기존 DB 접속 코드 4곳(감사·보관·Claude 로그인·Ollama) 통합: 새 공통 실행기는 이번 기능만 쓰고, 기존 사본은 손대지 않는다

## 9. 위험

- 관제소 DB 와 `GBRAIN_MEMBER_KEY_SECRET` 이 함께 새면 키도 샌다. 비밀 문구는 DB 와 다른 곳(서버 `.env`, GitHub Secret)에만 둔다.
