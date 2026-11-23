# gbrain MCP 토큰 관리 화면 설계

- 작성: 2026-11-22
- 이슈: Cassiiopeia/suh-project-control#207
- 앞 문서: [gbrain HTTP 서버 관제소 관리](2026-11-22-gbrain-http-server-control-tower-design.md) (#201), [gbrain 공개 MCP](2026-11-22-gbrain-public-mcp-design.md) (#204)
- 뒷 문서: [gbrain 팀 브레인 MCP](2026-11-23-gbrain-team-brain-mcp-design.md) (#210): 토큰 카드에 브레인 선택 (팀 브레인 기본 읽기 전용, 연결 이름 `gbrain-<project>`, 팀원 안내)

## 1. 왜

#204 로 `https://ai.suhsaechan.kr/mcp` 를 기기별 토큰으로 공개했지만, 토큰은 AI 서버 CLI(`gbrain auth create / list / revoke`)로만 다룰 수 있었다.
토큰에 익숙하지 않은 소유자가 관제소 화면에서 새 컴퓨터를 연결하고 안 쓰는 토큰을 끊게 한다.
#201 의 "하지 않는 것: 토큰 발급 화면" 결정을 이 문서가 바꾼다.

## 2. 목표 / 하지 않는 것

- 목표
  - 목록: 이름, id, 권한, 만든 때, 마지막 사용, 상태 (원문·해시 없음)
  - 발급: 기기 이름 `^[a-z0-9][a-z0-9-]{1,62}$`, 권한 선택지 2개(읽기+쓰기 기본, 읽기 전용)
    - 원문은 발급 응답·결과 창에서 1번만, 창을 닫으면 칸을 비움
    - 결과 창에 `claude mcp add` 한 줄, `mcpServers` 설정 조각, 연결 순서 안내
  - 폐기: 토큰 id 기준, 확인 창 (최근 24시간 안에 쓴 토큰은 연결이 끊긴다고 한 번 더 알림)
  - 감사: 발급·폐기를 `GBRAIN` 카테고리로 (이름·id·권한·IP·UA, 원문 없음)
- 하지 않는 것
  - 서버에서 CLI 실행 (gbrain 소유자 API 로 대체)
  - 권한 세부 조정(sources·takes holders·rescope): CLI 로 (`gbrain auth rescope`)
  - `/mcp` 공개 방식·새 공개 경로 변경
  - 토큰 자동 폐기 (`claude-code-mac` 은 소유자가 화면에서 정함)

## 3. 구조

```
브라우저 /admin/gbrain (카드 "MCP 토큰")
  ── apiFetch (X-API-Key) ── nginx /api/flask/ 키 검사 ──> Flask gbrain_token_router
       GET  /gbrain/tokens               목록 + 공개 MCP 주소
       POST /gbrain/tokens               발급 (GBRAIN_TOKEN_CREATE)
       POST /gbrain/tokens/<id>/revoke   폐기 (GBRAIN_TOKEN_REVOKE)
  > GbrainTokenService ── 127.0.0.1:3131 (gbrain 소유자 API)
       1) POST /admin/login {관리자 토큰}  > gbrain_admin 세션 쿠키 (메모리 캐시 23시간, 401 이면 1회 재로그인)
       2) GET /admin/api/api-keys · POST /admin/api/api-keys · POST /admin/api/api-keys/revoke {id}
```

- gbrain `POST /admin/api/api-keys` 는 `gbrain auth create` 와 같은 발급 함수(`mintLegacyToken`)를 씀: 기본 sources·takes holders(world) 동일
- 세션 쿠키는 gbrain 이 Secure 로 줄 수 있어 쿠키 저장소 대신 값만 꺼내 `Cookie` 헤더로 보냄
- 같은 이름의 사용 중 토큰이 있으면 409 `name_in_use` (gbrain 은 이름 중복을 허용하지만 화면에서 구분이 안 됨)
- 요청 위조 방지: 다른 관리 동작과 같음 (사용자 지정 `X-API-Key` 헤더 필수 > 다른 사이트가 보낼 수 없음)

### 원문(비밀값) 경로

| 위치 | 원문 |
|---|---|
| gbrain 발급 응답 > Flask 응답 본문 | 있음 (`Cache-Control: no-store`, `Pragma: no-cache`) |
| 결과 창 입력칸 | 있음, 창 닫으면 비움 |
| Flask 로그·감사 상세·URL·관제소 DB·파일 | 없음 (로그는 이름·id·권한만) |
| nginx 접근 로그 | 없음 (요청 줄만, 본문 미기록) |
| gbrain 로그 | 없음 (발급 경로가 원문을 기록하지 않음, gbrain 소스 주석) |

## 4. 이름

| 대상 | 이름 |
|---|---|
| 서비스 | `service/gbrain_token_service.py` `GbrainTokenService` (`list_tokens`, `create_token`, `revoke_token`) |
| 라우터 | `router/gbrain_token_router.py` `gbrain_token_bp` |
| 설정 | `config/gbrain_server_config.py` `GBRAIN_PUBLIC_MCP_URL`, `GBRAIN_OWNER_SESSION_REUSE_SECONDS` |
| 화면 | `templates/admin/gbrain.html` 카드 3, `static/js/gbrain-tokens.js` (카드·발급·폐기), `static/js/gbrain-token-result.js` (결과 창·복사, #213) |
| 감사 | `AuditAction.GBRAIN_TOKEN_CREATE`, `GBRAIN_TOKEN_REVOKE` |

## 5. 시험

- 단위 (`test_gbrain_token_service.py`): 목록 정렬·해시 미노출, 세션 재사용·만료 시 재로그인, 관리자 토큰 없음 503·거부 502·연결 실패, 발급 원문 반환·로그 미기록, 이름·권한 검증, 이름 중복 409, gbrain 400 사유 전달, 형식 밖 발급 응답 거부, 폐기 id·없음 404·이미 폐기 409·미적용 502
- 라우터 (`test_gbrain_token_router.py`): no-store, 공개 MCP 주소, 감사 상세에 원문 없음, 실패도 감사, 메서드 제한
- 배포 후 실측: 화면 API 로 시험 토큰 발급 > 공개 `/mcp` initialize 200 > 폐기 > 같은 요청 401 > 목록에서 폐기됨, Flask·nginx·gbrain 로그와 감사 기록에 원문 없음

## 6. 새 컴퓨터 연결 순서 (소유자용)

1. 관제소 > gbrain 서버 > "MCP 토큰" 카드 > **새 기기 연결**
2. 기기 이름(예: `home-macbook`)을 쓰고 권한은 기본(읽기 + 쓰기) 그대로 > **토큰 만들기**
3. 결과 창 "방법 1" 한 줄을 **복사** > 연결할 컴퓨터의 터미널에 붙여 넣고 Enter
   - 이미 gbrain 이 있다고 나오면 `claude mcp remove gbrain -s user` 후 다시
4. 그 컴퓨터의 Claude Code 를 모두 닫고 다시 열기 > `/mcp` 에서 gbrain connected 확인
5. 결과 창 닫기 (원문은 다시 볼 수 없음, 잃어버리면 폐기 후 새로 발급)
