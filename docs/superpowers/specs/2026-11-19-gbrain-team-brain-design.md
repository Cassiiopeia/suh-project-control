# gbrain 팀 브레인 (프로젝트별 공용 브레인, 관제소 권한 관리) 설계

- 작성: 2026-11-19
- 이슈: Cassiiopeia/suh-project-control#198
- 앞 문서: [AI 서버 공용 PG 관리](2026-11-19-ai-server-postgres-admin-design.md)
- 다음 문서: [gbrain HTTP 서버 관제소 관리](2026-11-22-gbrain-http-server-control-tower-design.md) (#201)
- 다음 문서: [gbrain 팀 브레인 MCP](2026-11-23-gbrain-team-brain-mcp-design.md) (#210): 팀원은 DB 마운트 대신 팀 브레인 MCP 서버(`/team/<project>/mcp`, 읽기 전용 토큰)로 붙음

> **2026-11-23 현황 (#218): 팀원 읽기 권한 기능 제거**
> - 이 문서의 "팀원 읽기 권한 주기·빼기"(화면 버튼·대화창, `PUT`/`DELETE /ai-db/databases/<db>/gbrain/readers/<role>`, `same_reader_writer`, SQL `grant_gbrain_reader`)는 걷어냄. 경로는 이제 404
> - 이유: 외부 `5432` 가 공유기에서 닫혀 쓸 수 없는 흐름을 화면이 안내했고, 팀원 계정에 `BYPASSRLS` 를 주는 경로 자체가 보안 위험. 점검 시 실제로 준 읽기 계정은 없었음
> - 대신: 팀원은 관제소 `/admin/gbrain` 토큰 카드에서 팀 브레인을 골라 받은 읽기 전용 토큰으로 `https://ai.suhsaechan.kr/team/<project>/mcp` 에 붙음 ([팀 브레인 MCP](2026-11-23-gbrain-team-brain-mcp-design.md), #210)
> - 남긴 것: 브레인 준비(쓰기 계정), 안전망 SQL `ai_db_ops.revoke_gbrain_reader` (화면·API 없음, 직접 호출). 설계 메모: [팀원 읽기 권한 제거](2026-11-23-remove-gbrain-team-reader-grant-design.md)

> **2026-11-23 현황 (#210)**
> - 5장 팀원 절차(외부 DB 직접 마운트)는 쓰지 않음: 팀 브레인마다 gbrain HTTP 서버를 두고 `https://ai.suhsaechan.kr/team/<project>/mcp` 에 읽기 전용 토큰으로 붙음
> - 새 팀 브레인은 관제소 "팀 브레인 만들기" 한 번으로 DB·쓰기 계정·브레인 준비·서비스·공개 경로까지 만듦 (passQL 도 이 흐름으로 옮김, DB 그대로)

> **2026-11-22 현황 (#201)**
> - "gbrain 원격 MCP 서버 운영 안 함" 결정은 바뀜: AI 서버 NSSM 서비스 `gbrain-http`(127.0.0.1:3131)가 소유자 맥의 Claude 세션용 MCP 를 맡음 (#204 부터 `https://ai.suhsaechan.kr/mcp` 를 기기별 토큰으로 공개, 맥은 공개 주소 사용)
> - 쓰기 계정 동기화 맥은 외부 `5432` 가 아니라 SSH 터널 `127.0.0.1:15433` 으로 접속 (passQL `~/gbrains/passql`)
> - 팀원 외부 접속 `ai.postgres.suhsaechan.kr:5432` 는 2026-11-22 실측에서 닫혀 있음 (#198 배포 직후엔 성공). 공유기 포워딩·DSM 확인 전까지 5장 팀원 절차는 동작하지 않음

## 1. 왜

프로젝트마다 gbrain 브레인 하나(`gbrain_<project>`)를 AI 서버 PG 에 두고, 팀원 모두가 같은 기억을 읽는다.
동기화(쓰기)는 한 계정이 맡고, 팀원은 읽기만 한다. 권한 주기·빼기는 관제소 "AI 서버 DB" 화면 한 곳에서 한다.

성공의 모습:
- 팀원이 인터넷 어디서든 `ai.postgres.suhsaechan.kr:5432`(TLS)로 프로젝트 브레인을 마운트해 키워드 검색
- 같은 팀원이 `https://ai.suhsaechan.kr/v1`(Ollama, `Authorization: Bearer <키>`)로 임베딩을 받아 의미 검색
- 읽기 팀원은 쓰기·표 만들기가 거부됨

## 2. 목표 / 하지 않는 것 / 실패로 보는 것

- 목표
  - 관제소: DB별 gbrain 상태(준비됨/미준비, 쓰기 계정, 읽기 팀원), 브레인 준비, 팀원 읽기 권한 주기·빼기
  - nginx: `X-API-Key` 없으면 `Authorization: Bearer <키>` 를 같은 키 목록으로 검사 (gbrain Ollama 클라이언트용)
- 하지 않는 것
  - gbrain 원격 MCP 서버 운영 (팀원은 각자 gbrain CLI 로 PG 직접 마운트)
  - 팀원별 Ollama 키 발급 화면: 키는 지금처럼 GitHub 비밀 `OLLAMA_API_KEY_LIST` 목록에 추가 > 배포
  - `ai_db_admin` 슈퍼유저 승격
  - 새 공개 경로 (nginx 키 검사 제외 경로 그대로)
- 실패로 보는 것
  - 읽기 팀원이 쓰기·`CREATE` 가능
  - 보호 DB(`gbrain`, `postgres`, `template*`)나 보호 계정(`gbrain`, `postgres`, `ai_db_admin`, `pg_*`)이 읽기·쓰기 계정으로 쓰임
  - 기존 `X-API-Key` 호출이 깨짐

## 3. 구조

```
쓰기 계정 (동기화 맥 1대, 1시간 주기)  ── 쓰기 ──┐
                                                ▼
팀원 gbrain (읽기 계정) ── TLS ──> ai.postgres.suhsaechan.kr:5432 > gbrain-postgres / gbrain_<project>
        │
        └── Bearer 키 ──> https://ai.suhsaechan.kr/v1 > nginx(키 검사) > Ollama (임베딩)

관제소 /ai-db/databases/<db>/gbrain*  > AiDbService (검증·보호 차단) > PgAdminClient
        > 대상 DB 에 접속해 ai_db_ops.<함수>() 호출 (SECURITY DEFINER, EXECUTE 는 ai_db_admin 만)
```

- gbrain 은 슈퍼유저 작업(확장, 이벤트 트리거, `BYPASSRLS`)이 필요하지만 `ai_db_admin` 은 슈퍼유저가 아님
  > 그 작업만 `sql/ai_db_ops_gbrain.sql` 의 함수 3개로 좁게 위임
  - `prepare_gbrain_database(writer)`: vector·pg_trgm·pgcrypto, RLS 자동 이벤트 트리거, 쓰기 계정 `BYPASSRLS`
  - `grant_gbrain_reader(reader, writer)`: CONNECT, public USAGE, 표·시퀀스 SELECT, 쓰기 계정 기준 기본 권한, `BYPASSRLS`
  - `revoke_gbrain_reader(reader, writer)`: 위의 역순
  - 함수가 직접 검사: 이름 규칙(42602), 계정 존재(42704), 슈퍼유저 아님·`ai_db_admin` 이 ADMIN 관리(42501)
- 읽기 팀원은 일반 "접속 권한 주기"를 쓰지 않음: 일반 권한은 public 스키마 `CREATE` 까지 줘서 쓰기 여지가 남음
  > 화면에서 두 흐름을 분리 (읽기 팀원은 일반 권한 목록·선택지에서 빠짐, 일반 권한 계정은 읽기 후보에서 빠짐)
- 접속은 TLS 필수: 연결 문자열 끝에 `?sslmode=require`

### API (전부 nginx `X-API-Key` 보호, 변경은 `@audited(AI_DB, ...)`)

| 메서드 | 경로 | 본문 | 하는 일 |
|---|---|---|---|
| GET | `/ai-db/databases/<db>/gbrain` | - | `is_ready`(ops 스키마·이벤트 트리거), `has_ops_functions`, `has_pages_table`, `writer_role`(`auto_enable_rls()` 소유자), `readers`(`public.pages` SELECT 계정, 쓰기·표 소유자 제외) |
| POST | `/ai-db/databases/<db>/gbrain/prepare` | `{writer_role}` | 브레인 준비 (`AI_DB_GBRAIN_PREPARE`) |
| PUT | `/ai-db/databases/<db>/gbrain/readers/<role>` | `{writer_role}` | 읽기 권한 주기 (`AI_DB_GBRAIN_READER_GRANT`) |
| DELETE | `/ai-db/databases/<db>/gbrain/readers/<role>` | `{writer_role}` | 읽기 권한 빼기 (`AI_DB_GBRAIN_READER_REVOKE`) |

| 오류 | 상태 | 상황 |
|---|---|---|
| `gbrain_ops_missing` | 409 | 그 DB 에 `ai_db_ops` 함수 없음 (PG 42883), 응답 `message` 에 설치 안내 |
| `same_reader_writer` | 400 | 읽기 = 쓰기 계정 (빼기 시 쓰기 계정 `BYPASSRLS` 까지 회수되는 것 방지) |
| `invalid_name` | 400 | 이름 규칙 위반 (PG 42602 포함), `writer_role` 누락 |
| `protected_object` | 403 | 보호 DB·계정 |
| `permission_denied` | 403 | `ai_db_admin` 관리 밖 계정 (PG 42501) |
| `not_found` | 404 | 없는 DB·계정 (DB 는 접속 전에 관리 DB 에서 확인) |

### nginx 키 검사

```
$http_authorization ─ "Bearer <토큰>" ─> $api_key_bearer
$http_x_api_key 있으면 그대로, 없으면 $api_key_bearer ─> $api_key_candidate
$api_key_candidate ─ {{OLLAMA_API_KEY_LIST}} (배포 시 "키" 1; 주입) ─> $api_key_valid
```

- `X-API-Key` 가 있으면 그것만 봄 (틀린 `X-API-Key` + 맞는 Bearer = 거부)
- `Bearer` 는 대소문자 무시, 토큰 뒤에 다른 값이 붙으면 거부, `Basic` 등 다른 방식은 무시
- 배포 워크플로우의 키 주입(`sed` 치환)은 그대로, 미리보기 `grep` 대상만 새 map 이름으로 변경

## 4. 설치 (운영자 1회, 슈퍼유저 `gbrain`)

```bash
# 새 DB 는 template1 에서 복사 > 함수도 함께 생김
docker exec -i gbrain-postgres psql -U gbrain -d template1 < sql/ai_db_ops_gbrain.sql
# 함수 추가 전에 만든 DB 는 DB 마다 1회
docker exec -i gbrain-postgres psql -U gbrain -d gbrain_<project> < sql/ai_db_ops_gbrain.sql
```

- 경로는 레포 `suh-ai-server/sql/ai_db_ops_gbrain.sql`
- 화면에 "관리 함수 없음" 또는 `gbrain_ops_missing` 이 보이면 그 DB 에 위 명령 실행

## 5. 프로젝트 브레인 만들기 · 팀원 붙이기

관제소 (운영자):
1. DB 만들기 `gbrain_<project>` + 쓰기 계정 접속 권한 (예: `<project>_writer`)
2. 그 DB 의 "브레인 준비" > 쓰기 계정 선택 > 쓰기 계정으로 gbrain 첫 동기화 (`pages` 표 생김)
3. 팀원 계정 만들기 `<project>_<name>` — **접속할 DB 는 고르지 않음** (고르면 일반 권한 = `CREATE` 포함)
4. 그 DB 의 "팀원 읽기 권한 주기" > 팀원 계정 선택
5. 비번·연결 문자열(1회 표시)과 Ollama 키(GitHub 비밀 목록에 넣고 배포한 것)를 팀원에게 전달

팀원:
1. 개인 브레인이 없을 때만 `gbrain init`
2. 프로젝트 브레인 마운트 (읽기 전용)
   ```bash
   gbrain mounts add <project> --path ~/gbrains/<project> --engine postgres \
     --db-url 'postgresql://<role>:<pw>@ai.postgres.suhsaechan.kr:5432/gbrain_<project>?sslmode=require'
   ```
3. 의미 검색용 임베딩 (없어도 키워드 검색은 동작)
   ```bash
   export OLLAMA_BASE_URL=https://ai.suhsaechan.kr/v1
   export OLLAMA_API_KEY=<발급받은 키>   # nginx 가 Authorization: Bearer 로 검사
   ```

## 6. 시험

- 단위 (pytest, 가짜 PG 클라이언트): 보호 DB·계정 차단(읽기·쓰기 양쪽), 이름 규칙, 읽기 = 쓰기 거부, ops 미설치 409, 감사 기록, 읽기 권한이 일반 grant 를 부르지 않음, 함수 인자 `sql.Literal`·대상 DB 접속, 없는 DB 접속 전 404, 준비 판정
- nginx 규칙 테스트: Bearer 추출 map, `X-API-Key` 우선, 키 목록 자리 1곳
- 배포 후 실측: `Authorization: Bearer <키>` 로 `https://ai.suhsaechan.kr/v1/models` 200, 키 없음 401, 기존 `X-API-Key` 호출 유지 / 읽기 계정으로 외부 접속 > SELECT 성공 > INSERT·CREATE TABLE 거부

## 7. 구현자 판단으로 남긴 것

- `is_ready` = ops 스키마 + 이벤트 트리거 (첫 동기화 전 `pages` 표 없음은 `has_pages_table` 로 따로 표시, 읽기 목록만 비어 있음)
- `same_reader_writer` 오류 추가
- 화면: DB 카드 안 gbrain 줄 (배지·쓰기 계정·읽기 팀원), 모달 하나로 준비/읽기 권한 공용
