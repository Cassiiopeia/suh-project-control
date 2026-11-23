# gbrain 팀원 DB 직접 읽기 권한 제거 설계 메모

- 작성: 2026-11-23
- 이슈: Cassiiopeia/suh-project-control#218
- 승인: 소유자 (제거 결정)
- 앞 문서: [팀 브레인 DB·권한](2026-11-19-gbrain-team-brain-design.md) (#198), [팀 브레인 MCP](2026-11-23-gbrain-team-brain-mcp-design.md) (#210)

## 1. 왜

- #198 은 팀원 계정에 브레인 DB 읽기 권한(`BYPASSRLS` 포함)을 주고 `ai.postgres.suhsaechan.kr:5432` 로 바로 붙게 했다.
- 그 포트는 공유기에서 닫혔고, 팀원은 #210·#213 부터 팀 브레인 MCP(`/team/<project>/mcp`, 읽기 전용 토큰)로 붙는다.
- 그런데 AI 서버 DB 화면은 여전히 "팀원 읽기 권한 주기" 버튼과 "gbrain 팀원은 읽기 권한으로 따로 줘요" 안내를 보여 줬다. 쓸 수 없는 흐름이라 헷갈리고, `BYPASSRLS` 를 주는 경로가 열려 있는 것 자체가 보안 위험이다.
- 정리 점검에서 실제로 준 읽기 계정은 없었다.

## 2. 하는 것 / 남기는 것 / 하지 않는 것

| 구분 | 대상 |
|---|---|
| 걷어냄 | 화면: 팀원 읽기 권한 주기 버튼·대화창 모드, 읽기 팀원 배지·빼기 버튼, 안내 문구 |
| 걷어냄 | API: `PUT`/`DELETE /ai-db/databases/<db>/gbrain/readers/<role>` (이제 404), 오류 `same_reader_writer` |
| 걷어냄 | 서비스·PG 클라이언트: `grant_gbrain_reader`, `revoke_gbrain_reader`, 읽기 팀원 조회(`readers`) |
| 걷어냄 | SQL: `ai_db_ops.grant_gbrain_reader` (`DROP FUNCTION IF EXISTS`, 파일을 다시 실행하면 기존 DB 에서도 지움) |
| 바꿈 | DB 화면 안내: 팀원은 `gbrain 서버` 화면의 팀 브레인 읽기 전용 토큰으로 연결 (DB 카드 gbrain 줄에 같은 링크) |
| 남김 | 브레인 준비(쓰기 계정) 흐름, `AI_DB_GBRAIN_PREPARE` 감사 |
| 남김 | 안전망 SQL `ai_db_ops.revoke_gbrain_reader(reader, writer)`: 화면·API 없음, 남은 권한이 발견되면 직접 호출 |
| 남김 | 감사 행위 코드 `AI_DB_GBRAIN_READER_GRANT`/`REVOKE`: 과거 기록 표시·검색용 (라벨에 "제거된 기능") |
| 남김 | 서비스 계정 `passql_writer`, `ai_db_admin`, `gbrain` / 시험 계정 `elum_member` (#198 산출물인지 확인 안 됨, 손대지 않음) |
| 하지 않음 | 팀 브레인 MCP·토큰 흐름 변경, 공유기 포트 변경 |

## 3. 검증

- 단위: 읽기 권한 경로 `PUT`/`DELETE` 404 + 클라이언트 호출·감사 기록 없음, 서비스·클라이언트에 주기·빼기 메서드 없음, gbrain 상태에 `readers` 없음, DB 화면에 옛 안내·버튼 없음과 팀 브레인 토큰 안내 있음, 브레인 준비 검증·감사 유지
- 배포 후: 실제 관리 화면에서 버튼·문구 사라짐, 읽기 권한 경로 404, `/team/<project>/mcp`·`/mcp` 상태 코드 그대로
