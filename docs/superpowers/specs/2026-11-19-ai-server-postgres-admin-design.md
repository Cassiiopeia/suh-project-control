# AI 서버 공용 PG 관리 (프로젝트별 DB·계정) 설계

- 작성: 2026-11-19
- 출발점: Twin-Fang/elum#1485 (개인 gbrain 을 윈도우 AI 서버 PG 로 이전)

> **2026-11-23 현황 (#218)**: DB 화면의 "gbrain 팀원은 읽기 권한으로 따로 줘요" 안내와 팀원 읽기 권한 주기(#198)는 걷어냄.
> 팀원은 DB 계정 대신 `/admin/gbrain` 의 팀 브레인 읽기 전용 토큰(`/team/<project>/mcp`, #210)으로 연결. 외부 `5432` 는 공유기에서 닫혀 있음.
> 상세: [팀원 읽기 권한 제거](2026-11-23-remove-gbrain-team-reader-grant-design.md)

> **2026-11-22 현황 (#201)**: 아래 "gbrain 원격 MCP 서버 운영" 제외 결정은 바뀜.
> 소유자 맥 전용 MCP 서버를 AI 서버에 둠 ([gbrain HTTP 서버 관제소 관리](2026-11-22-gbrain-http-server-control-tower-design.md)). 팀원 원격 MCP·팀원별 토큰은 여전히 범위 밖

## 1. 왜

윈도우 AI 서버의 PG(pgvector 포함)를 시놀로지 PG 처럼 **외부에서 아이디·비번으로 쓰는 공용 DB** 로 연다.
프로젝트마다 DB 와 계정을 따로 주고, 관제소 관리 화면 한 곳에서 만들고·권한 주고·비번 바꾸고·지운다.
첫 용도는 프로젝트별 gbrain(에이전트 기억) DB 이고, 다른 서비스도 같은 방식으로 쓴다.

성공의 모습:
- 관리 화면에서 "DB 만들기 + 계정 만들기 + 연결" 후 나온 연결 문자열을 팀원 gbrain/서비스에 넣으면 바로 동작
- 계정은 허락된 DB 에만 들어가고, 개인 DB·시스템 DB 는 화면에서도 손댈 수 없음

## 2. 목표 / 하지 않는 것 / 실패로 보는 것

- 목표
  - 외부 주소 `ai.postgres.suhsaechan.kr:5432` (구성 완료, 2026-11-19)
  - 관제소 "AI 서버 DB" 화면·API: DB 목록·생성·삭제, 계정 목록·생성·비번 재발급·삭제, DB 접속 권한 주기·빼기, 연결 문자열 복사
  - 관리 전용 PG 계정 `ai_db_admin` (CREATEDB·CREATEROLE, 슈퍼유저 아님)
- 하지 않는 것
  - gbrain 원격 MCP 서버 운영 (브레인 서버 안은 사용자가 철회)
  - IP 자동 차단 (Docker Desktop 이 원 IP 를 가림) > 긴 무작위 비번 + `auth_delay` 2초로 대신
  - 별도 관리자 로그인: 기존 nginx `X-API-Key` 유지 (사용자 결정, 키를 아는 사람은 DB 계정도 관리 가능함을 인지)
- 실패로 보는 것
  - 화면에서 개인 DB `gbrain`, 시스템 DB(`postgres`, `template*`), 보호 계정(`gbrain`, `ai_db_admin`, `postgres`)이 바뀜
  - 비번이 로그·감사 기록·화면 재조회로 노출
  - PG 장애가 관제소 다른 기능을 막음
  - 기존 시놀로지·AI 서버 서비스(TTS, Ollama, nginx) 영향

## 3. 현재 구성 (2026-11-19 완료)

| 항목 | 값 |
|---|---|
| 외부 주소 | `ai.postgres.suhsaechan.kr` (Cloudflare CNAME → `suh-project.synology.me`, DNS 전용) |
| 공유기 | KT 포트포워딩 외부 TCP 5432 → 172.30.1.14:5433 (`AI_POSTGRES`). 기존 규칙·DMZ(→172.30.1.99) 유지. 5432 는 이전에 응답 없던 포트 |
| PG | 윈도우 Docker `gbrain-postgres` (pgvector:pg17, 볼륨 `gbrain-pgdata`, `0.0.0.0:5433`, `restart unless-stopped`) |
| 보호 설정 | `auth_delay` 2000ms, `log_connections`, scram-sha-256, pg_hba: `gbrain` DB 는 `gbrain` 계정만 |
| 기존 DB | `gbrain` (개인 브레인), `gbrain_elum` + 계정 `elum_member` (시험용) |

## 4. 검토한 안

| 안 | 판단 |
|---|---|
| gbrain 원격 MCP 서버 + 팀원별 토큰 | 사용자 철회: 공용 PG 로 단순하게 |
| **PG 직접 공개 + 관제소에서 DB·계정 관리 (선택)** | 시놀로지 PG 와 같은 사용법, gbrain 외 서비스도 사용 |
| 슈퍼유저로 관리 | ❌ 관제소 키 노출 시 피해 범위 큼 > `ai_db_admin` (CREATEROLE 은 PG16+ 에서 자기가 만든 계정만 관리) |

## 5. 구조

```
관제소 Flask (윈도우, NSSM)
  router/ai_db_router.py      /ai-db/*  (nginx X-API-Key 보호)
  service/ai_db/
    ai_db_service.py           검증 > 보호 대상 차단 > 실행 > 감사
    pg_admin_client.py         psycopg2, autocommit, sql.Identifier 로만 이름 조립
  templates/admin/ai_db.html + static/js/ai-db.js
        │  postgresql://ai_db_admin@127.0.0.1:5433/postgres
        ▼
  gbrain-postgres (Docker)
```

- 접속 정보: 환경변수 `AI_DB_ADMIN_URL`, 없으면 파일 `C:/AI/secrets/ai-db-admin-url` (배포 시 덮어쓰지 않는 위치. CI 비밀 `FLASK_ENV_FILE` 은 손대지 않음)
- 외부 표시용 주소: 환경변수 `AI_DB_PUBLIC_HOST` 기본 `ai.postgres.suhsaechan.kr`, 포트 5432
- 관리 대상 = `ai_db_admin` 이 만든(또는 ADMIN 권한 받은) 계정과 소유 DB 만. 이름 규칙 `^[a-z][a-z0-9_]{2,40}$`
- 보호 목록 (코드 상수): DB `gbrain`, `postgres`, `template0`, `template1` / 계정 `gbrain`, `postgres`, `ai_db_admin`, `pg_*`

### API

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/ai-db/status` | 연결 상태, 서버 버전, 외부 주소 |
| GET | `/ai-db/databases` | 관리 DB 목록 (크기, 소유 계정, 접속 가능 계정) |
| POST | `/ai-db/databases` | DB 생성 (`name`, 선택 `owner_role`), `vector` 확장 설치, PUBLIC 접속 회수 |
| DELETE | `/ai-db/databases/<name>` | 삭제 (본문 `confirm_name` 일치 필요) |
| GET | `/ai-db/roles` | 관리 계정 목록 |
| POST | `/ai-db/roles` | 계정 생성, 비번 무작위 생성 > 응답에 **한 번만** 비번·연결 문자열 |
| POST | `/ai-db/roles/<name>/password` | 비번 재발급 (한 번만 노출) |
| DELETE | `/ai-db/roles/<name>` | 삭제 (`confirm_name`) |
| PUT | `/ai-db/databases/<db>/grants/<role>` | 접속 권한 주기 (CONNECT + public 스키마 사용·생성) |
| DELETE | `/ai-db/databases/<db>/grants/<role>` | 권한 빼기 |

- 모든 변경 API `@audited(AuditCategory.AI_DB, ...)`, 상세에 이름만 (비번 제외)
- 오류: `{"error": "snake_code"}` + 상태 코드. 예 `ai_db_unavailable` 503, `invalid_name` 400, `protected_object` 403, `not_found` 404, `already_exists` 409, `confirm_mismatch` 400

### 화면

```
[AI 서버 DB]   ● 연결됨 · PostgreSQL 17.12 · ai.postgres.suhsaechan.kr:5432
┌ 데이터베이스 ───────────────┐ ┌ 계정 ───────────────────────┐
│ gbrain_elum  12MB  elum_member│ │ elum_member  [비번 재발급][삭제]│
│   접속 가능: elum_member [+]  │ │ [+ 계정 만들기]               │
│ [+ DB 만들기]                 │ └──────────────────────────────┘
└──────────────────────────────┘
비번은 만들 때 한 번만 표시 (연결 문자열 복사 버튼)
```

## 6. 실패 경로

| 상황 | 처리 |
|---|---|
| 관리 접속 정보 없음 / PG 다운 | 화면 "연결 안 됨 (E-AIDB-503)", API 503, 다른 관제소 기능 정상 |
| 보호 대상 요청 | 403 `protected_object`, 감사 실패 기록 |
| 이름 규칙 위반 | 400 `invalid_name` |
| 삭제 확인 불일치 | 400 `confirm_mismatch` |
| 접속 중인 DB 삭제 | `WITH (FORCE)` 쓰지 않음 > 409 `database_in_use` |

## 7. 시험

- 단위 (pytest, 가짜 PG 클라이언트): 이름 검증, 보호 대상 차단, 비번 1회 노출·로그 미포함, 503 처리, 감사 기록, 삭제 확인
- 배포 후 실측: `/ai-db/status` 연결됨, 시험 DB·계정 생성 > 외부 `ai.postgres.suhsaechan.kr` 접속 > 다른 DB 거부 > 정리, 기존 Flask·TTS 응답 유지

## 8. 구현자 판단으로 남긴 것

- 화면 세부 배치 (기존 관제소 결: daisyUI 5, Lucide)
- 권한 부여 범위 세부 SQL (CONNECT, `public` 스키마 USAGE·CREATE 기본)
