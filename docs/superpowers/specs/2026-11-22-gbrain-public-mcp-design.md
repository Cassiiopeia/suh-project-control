# gbrain 공개 MCP 설계

- 작성: 2026-11-22
- 이슈: Cassiiopeia/suh-project-control#204
- 앞 문서: [gbrain HTTP 서버 관제소 관리](2026-11-22-gbrain-http-server-control-tower-design.md) (#201)
- 뒷 문서: [gbrain MCP 토큰 관리 화면](2026-11-22-gbrain-token-management-design.md) (#207): 토큰 목록·발급·폐기를 관제소 화면에서

## 1. 왜

#201 까지 맥 Claude 는 SSH 터널(127.0.0.1:3131)로만 gbrain MCP 에 붙었다.
터널이 끊기면 모든 세션의 gbrain 이 함께 끊기고, 다른 기기는 터널을 따로 만들어야 한다.
소유자 승인으로 `https://ai.suhsaechan.kr/mcp` 를 **인증 필수**로 공개한다.

## 2. 목표 / 하지 않는 것

- 목표
  - 공개 주소 `/mcp` 하나만 gbrain 으로 프록시 (토큰 없음·임의·폐기 토큰 401)
  - 기기별 긴 무작위 gbrain 접근 토큰 (사람 비밀번호 안 씀, 기기 단위로 폐기)
  - nginx 바깥 필터: Bearer 형식, POST 만, 속도 제한, 본문 상한, 로그에 토큰 미기록
- 하지 않는 것
  - OAuth 2.1 경로(`/authorize`·`/token`·`/register`)·`/.well-known/*` 공개 (Claude Code 는 고정 Bearer 헤더로 충분)
  - `/admin` 변경 (관제소 게이트 쿠키 그대로), Postgres·Ollama 추가 노출
  - gbrain 자체 속도 제한 env (`GBRAIN_HTTP_RATE_LIMIT_*`): nginx 가 맡음, 서비스 설정은 그대로

## 3. 구조

```
맥/기기 Claude ── https://ai.suhsaechan.kr/mcp (Authorization: Bearer <기기 토큰>)
  > Cloudflare (CF-Connecting-IP 덮어씀) > NAS 리버스 프록시 172.30.1.99 > nginx 11435
      location = /mcp
        1) POST 아니면 405
        2) Authorization 이 "Bearer <값>" 아니면 401 (gbrain 까지 안 감)
        3) 속도 제한 2개: 실제 접속 IP 10r/s burst 40, NAS 경유 전체 30r/s burst 120 (초과 429)
        4) 본문 4MB, 로그 형식 mcp ($uri 만, Authorization 없음)
  > gbrain-http 127.0.0.1:3131 POST /mcp  (MCP SDK requireBearerAuth: 토큰 조회·폐기·scope 검사, 1차 인증)
```

- nginx 는 모든 접속을 NAS IP 로 봄 (2026-11-22 접근 로그 실측: 3,000줄 중 2,996줄 172.30.1.99)
  > 실제 IP 키 = `CF-Connecting-IP`, 없으면 접속 IP. Cloudflare 를 우회해 원본에 직접 오며 헤더를 위조해도 NAS 경유 전체 상한이 막음
- 토큰 없는 요청은 `if ... return 401` 이 속도 제한(preaccess)보다 먼저 끝남 > 비용 없는 401. 토큰이 붙은 요청만 gbrain DB 조회를 하므로 속도 제한 대상
- `location = /mcp` 의 `add_header WWW-Authenticate` 가 server 공통 CORS `*` 상속을 끊음 (gbrain 기본값처럼 브라우저 출처 거부)
- `GET /mcp` 는 gbrain 도 405 (상태 없는 전송, SSE 역채널 없음) > nginx 에서 바로 405

## 4. 토큰

| 이름 | 기기 | scopes | 저장 위치 |
|---|---|---|---|
| `claude-code-mac-public` | 소유자 맥 (`~/.claude-b`, `~/.claude-d`) | read,write | Claude 설정 파일(600) 의 `mcpServers.gbrain.headers`, 서버 DB(해시) |
| `claude-code-mac` | 소유자 맥 터널용 (#201) | read,write | 실행 중 세션이 끝나면 관제소 화면에서 폐기 (소유자 판단) |

- 발급·폐기: 관제소 `/admin/gbrain` "MCP 토큰" 카드 (#207). 원문은 발급 직후 1번만 보이고, 결과 창의 `claude mcp add` 한 줄로 기기에 넣음
  - CLI 도 그대로 됨: `gbrain auth create <기기 이름> --scopes read,write` (맥 CLI 도 같은 DB 에 씀), 출력은 화면·파일에 남기지 않고 바로 설정에 넣음
- 새 기기 = 새 토큰. 기기 분실·교체 시 그 토큰만 폐기 (화면에서 id 기준, CLI 는 `gbrain auth revoke --id <uuid>`)

## 5. 시험

- 단위 (`test_control_tower_nginx.py`): gbrain 경로는 `/admin` 2개 + `= /mcp` 뿐, OAuth·discovery 미노출, POST·Bearer 검사가 프록시보다 먼저, 속도 제한 2개·429·4MB, 로그 형식에 쿼리·Authorization 없음, CORS `*` 미상속
- 배포 후 실측: 토큰 없음·임의·폐기 토큰 401, 맥 토큰 initialize 200, 연속 요청 429, 접근·오류 로그에 토큰 값 없음, 터널 3131 포워딩 없이 Claude 세션 `recall`·`remember`·`context_pack` 동작

## 6. 롤백

- 맥: `~/.gbrain/remote/ROLLBACK.md` (설정 URL 을 터널 `http://127.0.0.1:3131/mcp` 로 되돌림, 터널 3131 포워딩은 남아 있음)
- 서버: `location = /mcp` 블록을 지우고 재배포 > `/mcp` 는 다시 `location /` 의 키 검사로 401
