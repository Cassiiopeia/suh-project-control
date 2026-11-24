# 팀 브레인 만들기: 기존 DB 받아 쓰기, 권한 재적용, 삭제 금지, dry_run (#226)

- 작성: 2026-11-24
- 이슈: Cassiiopeia/suh-project-control#226
- 앞 문서: [팀 브레인 MCP 설계](2026-11-23-gbrain-team-brain-mcp-design.md) (#210)

## 1. 왜

elum 수동 실행(2026-11-24)에서 `gbrain_elum` 이 비어 있고 준비가 안 된 상태였는데, 흐름이 받아 쓰지 못해 멈췄다.
그 뒤 DB 를 지우고 다시 만들면서 기존 쓰기 계정의 접속 권한이 사라졌고, `gbrain init` 이 실패했다.
원인 2개: (1) 이미 있는 DB 를 판정·준비하는 단계가 없음 (2) 쓰기 계정 권한을 계정을 새로 만들 때만 줌.

## 2. 만들기 흐름 (`POST /gbrain/teams`)

| 단계 | 하는 일 | 다시 실행 |
|---|---|---|
| database | 검사(카탈로그만) > 판정 > 없음: 생성 / 빈 DB: 받아 씀 / gbrain DB: 그대로 / 알 수 없음: 멈춤 | `created` · `adopted` · `kept` |
| database_repair | 받아 쓸 DB 의 소유자가 `ai_db_admin` 이 아니거나 `ai_db_ops` 가 없으면 슈퍼유저로 손봄 | 필요할 때만 (`owner_changed`, `ops_installed`) |
| writer_role | 없으면 생성 (새 비번 1회), 있으면 비번 그대로 | `created` · `kept` |
| grants | CONNECT, public USAGE·CREATE, 관리 계정 소유 표·시퀀스 ALL, 기본 권한 | 매번 `reapplied` |
| prepare | `ai_db_ops.prepare_gbrain_database` (확장·RLS 트리거·BYPASSRLS) | `prepared` · `reapplied` |
| 이후 | 등록·관리자 토큰·설정·서비스·nginx·감시 (#210 과 같음) | |

### 판정 (검사는 표 데이터를 읽지 않음)

- 알 수 없음: public 이 아닌 스키마(`ai_db_ops` 제외), 쓰기 계정이 아닌 소유자의 public 관계, 쓰기 계정이 아닌 소유의 public 함수(확장 소속·`auto_enable_rls` 제외), 안을 볼 수 없음
- 빈 DB: 위가 없고 public 관계 0개
- gbrain DB: 위가 없고 public 관계가 전부 쓰기 계정 소유
- 관리 계정이 접속 못 하는 DB 는 슈퍼유저(개인 브레인 설정의 DSN)로 같은 검사만 함

### 슈퍼유저를 쓰는 범위

`ai_db_admin` 은 슈퍼유저가 아니라 다른 계정이 만든 DB 의 소유·`ai_db_ops` 설치를 할 수 없다.
빈 DB·gbrain DB 로 판정된 뒤에만 2가지를 한다: `ALTER DATABASE ... OWNER TO ai_db_admin`, `sql/ai_db_ops_gbrain.sql` 실행 (원래 수동 절차와 같은 파일).
그 외 권한·준비는 모두 `ai_db_admin` 과 SECURITY DEFINER 함수로 한다.

### 삭제 금지

- 팀 흐름 코드·SQL 문장에 DB·계정·스키마·표 DROP/TRUNCATE 와 삭제 호출이 없다 (`test_gbrain_team_no_drop.py` 가 파일·메서드·SQL 상수를 검사)
- DB 생성 뒤 실패해도 되돌려 지우지 않는다 (다음 실행이 받아 씀). 기존 `create_database`·`create_role` 의 되돌리기 삭제는 AI DB 화면 전용으로 남김
- 준비 SQL 파일의 DROP 은 #218 에서 없앤 옛 함수 정리 1줄(`DROP FUNCTION IF EXISTS ai_db_ops.grant_gbrain_reader`)뿐이며 시험으로 고정

## 3. HTTP 계약 (nginx `/api/flask` 뒤, `X-API-Key`)

### POST `/gbrain/teams`

요청: `{"project": "passql", "writer_password": "선택", "dry_run": false}` (`dry_run` 은 bool 만, 아니면 400 `invalid_dry_run`)

성공 (만들기): `{"success": true, "brain": {...}, "steps": {...}, "writer_secret": {...새 계정일 때만}}`

성공 (dry_run, 감사 기록 없음, 아무것도 바꾸지 않음):

```json
{"success": true, "dry_run": true, "can_create": true,
 "brain": {"project", "mcp_url", "mcp_server_name", "database_name", "writer_role", "service_name", "port",
           "is_registered", "gbrain_home", "nginx_map_path"},
 "plan": {"database", "writer_role", "grants", "prepare", "admin_token", "config", "service", "nginx"},
 "blockers": [{"code", "error", "next_step", "found?"}],
 "details": {"database_kind", "database_owner", "database_repairs", "writer_role_exists", "service_state"}}
```

계획 값: `exists` · `would_create` · `would_adopt` · `would_regrant` · `refuse`

실패 (만들기·dry_run 공통): `{"success": false, "error": "해요체 문구", "code", "next_step", "steps", "failed_step", "cause?", "found?", "writer_secret?"}`
dry_run 실패는 `"dry_run": true` 를 함께 싣는다. 코드별 다음 할 일은 `service/gbrain_team_errors.py` 의 표가 원본이다.

## 4. 시험

- `test_gbrain_team_adopt_and_dry_run.py`: 판정, 빈 DB 받아 쓰기, 슈퍼유저 손보기, 권한 재적용, 알 수 없는 DB 거부(변경 0), 계정 거부, 단계별 실패 응답, dry_run 변경 0
- `test_gbrain_team_pg_client.py`: 검사 SQL(Literal·카탈로그만), 생성 되돌리기 없음, 권한 문장, 손보기, 3F000 변환
- `test_gbrain_team_no_drop.py`: 삭제 금지 고정
- 로컬 PG 18 임시 클러스터 실측: 새 DB·빈 DB 손보기·알 수 없는 DB·다시 실행 후 데이터 유지
