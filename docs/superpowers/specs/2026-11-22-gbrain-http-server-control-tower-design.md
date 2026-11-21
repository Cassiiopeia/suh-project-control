# gbrain HTTP 서버 관제소 관리 설계

- 작성: 2026-11-22
- 이슈: Cassiiopeia/suh-project-control#201
- 앞 문서: [gbrain 팀 브레인](2026-11-19-gbrain-team-brain-design.md) (#198)
- 뒷 문서: [gbrain 공개 MCP](2026-11-22-gbrain-public-mcp-design.md) (#204): `/mcp` 를 기기별 토큰으로 공개, 맥은 터널 대신 공개 주소 사용
- 뒷 문서: [gbrain MCP 토큰 관리 화면](2026-11-22-gbrain-token-management-design.md) (#207): 토큰 목록·발급·폐기를 이 관리 화면에서

## 1. 왜

맥에서 Claude 세션마다 `gbrain serve`(stdio, 개당 약 80~130MB)가 떠서 세션 9~12개면 0.7~1GB를 썼다.
MCP 서버를 AI 서버의 상시 서비스 하나로 옮겼고, 맥은 기존 SSH 터널로 붙는다.
관제소가 이 서비스를 다른 Windows 서비스(Sunshine 등)와 같은 방식으로 관리하고, gbrain 관리자 화면에 바로 들어가게 한다.

## 2. 목표 / 하지 않는 것

- 목표
  - 서비스 관리: 상태, 헬스, 버전, 시작/중지/재시작, 최근 로그, 사용하는 DB·임베딩 모델
  - 관제소 감시 등록: `services.yml` 내부 점검 `http://127.0.0.1:3131/health`
  - gbrain `/admin` 로그인 버튼: 관제소 관리자 인증 뒤에서만, 1회용 링크를 서버가 열어 보거나 기록하지 않음
  - 서비스 설치 스크립트 (`scripts/setup-gbrain-http.ps1`): 다시 설치해도 같은 결과
  - #198 문서를 실제 운영과 맞춤
- 하지 않는 것
  - `/mcp` 외부 공개 (맥은 SSH 터널 127.0.0.1:3131 로만 접속) > #204 에서 인증 필수로 공개함
  - gbrain MCP 토큰 발급 화면 (`gbrain auth create` 를 서버·맥 CLI 로) > #207 에서 관리 화면에 추가함
  - 팀원 외부 접속 경로 복구 (공유기 포워딩 문제, 6장)

## 3. 구조

```
맥 Claude ── SSH 터널 127.0.0.1:3131 ──> gbrain-http (NSSM, LocalSystem, 127.0.0.1:3131)
   (#204 이후: 맥 Claude ── https://ai.suhsaechan.kr/mcp + 기기 토큰 ── nginx = /mcp ──> gbrain-http)
                                             ├─ Postgres gbrain-postgres 127.0.0.1:5433 / gbrain
                                             └─ Ollama 127.0.0.1:11434 (qwen3-embedding:0.6b, 1024차원)

브라우저 ── https://ai.suhsaechan.kr ── nginx 11435
   /api/flask/gbrain/*  (X-API-Key) ──> Flask GbrainServerService ── 서비스 제어·헬스·로그·설정 요약
   /admin/*  (게이트 쿠키, auth_request) ──> gbrain-http   (/.well-known·OAuth 은 프록시 안 함)
   = /mcp    (Bearer 필수, 속도 제한, #204) ──> gbrain-http
```

### 서비스 설치 (`scripts/setup-gbrain-http.ps1`, 관리자 1회)

- bun + gbrain(고정 커밋) 설치, `GBRAIN_HOME`(기본 `C:\Users\kimchi`) 의 `.gbrain\config.json` 사용
- 관리자 토큰 `C:\AI\secrets\gbrain-admin-bootstrap-token`: 없을 때만 생성, SYSTEM·Administrators 만 읽기
- 실행기 `C:\AI\gbrain\run-gbrain-http.cmd`(레포 `scripts/gbrain/` 원본 복사): 토큰 파일 > `GBRAIN_ADMIN_BOOTSTRAP_TOKEN` > `gbrain serve --http --bind 127.0.0.1 --port 3131 --suppress-bootstrap-token`
  - 배포가 덮어쓰는 `C:\AI\suh-ai-server` 밖에 둠 (실행 중인 cmd 파일 교체 방지)
- NSSM `gbrain-http`: 자동 시작, 비정상 종료 시 재시작(지연 0), 로그 `C:\AI\gbrain\logs\gbrain-http.log` 10MB 회전
- 정지: NSSM 2.24 가 bun 종료 뒤 `StopPending` 에 멈추는 경우가 있음 (실측: 재시작 지연 5000 이면 거의 매번, 0 이어도 간헐)
  > 정지 요청 후 8초 안에 안 멈추면 그 서비스의 NSSM 래퍼 프로세스만 종료 (`WindowsServiceClient(forced_stop_after_seconds=8)`, 설치 스크립트도 같은 방식)

### API (nginx `X-API-Key`, 변경은 `@audited(GBRAIN, ...)`)

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/gbrain/status` | 서비스 상태, 헬스(버전·설치 버전·재시작 필요), DB(호스트·포트·DB·계정, 비번 제외), 임베딩 모델·차원, 관리자 토큰 준비 여부 |
| GET | `/gbrain/logs?lines=` | 로그 파일 끝 N줄 (최대 500) |
| POST | `/gbrain/control/<start\|stop\|restart>` | 서비스 제어 (`GBRAIN_START/STOP/RESTART`) |
| POST | `/gbrain/admin-login` | 1회용 로그인 경로 발급 + 게이트 쿠키 (`GBRAIN_ADMIN_LOGIN`) |
| GET | `/gbrain/admin-gate` | 게이트 쿠키 검사 (nginx `auth_request` 전용, 204/401) |

### 관리자 로그인 흐름

1. 관리 화면 버튼 > `apiFetch POST /gbrain/admin-login` (관제소 `X-API-Key` 인증)
2. Flask: 토큰 파일 > gbrain `POST /admin/api/issue-magic-link` > 응답 `url` 에서 경로만 추출, `^/admin/auth/[0-9a-f]{64}$` 검사
   - 링크를 GET 하지 않음, 로그·감사 상세에 넣지 않음
3. Flask: 게이트 쿠키 `ct_gbrain_admin_gate` = `만료시각.HMAC-SHA256(토큰, 만료시각)`, `Path=/`, HttpOnly, Secure, SameSite=Strict, 12시간
   - Secure 라 https 주소(`ai.suhsaechan.kr`)에서만 동작 (LAN http 접속은 게이트 통과 불가)
   - 따로 비밀값을 두지 않고 관리자 토큰을 HMAC 키로 씀 (토큰 교체 = 게이트 무효)
4. 브라우저가 `/admin/auth/<nonce>` 로 이동 > nginx `auth_request` 게이트 통과 > gbrain 이 쿠키 `gbrain_admin` 발급 > `/admin/`
   - `/admin/auth/` 는 `access_log off` (사용 후라도 nonce 를 남기지 않음)
   - nginx `proxy_cookie_flags gbrain_admin secure` (gbrain 은 http 로 보고 Secure 를 안 붙임)

## 4. 이름

| 대상 | 이름 |
|---|---|
| Windows 서비스 제어 공통 | `util/windows_service_client.py` `WindowsServiceClient` (Sunshine 도 이걸 씀) |
| gbrain 서비스 | `service/gbrain_server_service.py` `GbrainServerService` |
| 게이트 쿠키 | `service/gbrain_admin_gate.py` `create_gate_cookie_value`, `is_gate_cookie_valid` |
| 설정 | `config/gbrain_server_config.py` |
| 라우터·화면 | `router/gbrain_router.py`, `/admin/gbrain`, `static/js/gbrain.js` |

## 5. 시험

- 단위: 상태 조립(비번 미노출), 헬스 실패 시에도 상태 응답, 로그 줄 수 상한, 제어 감사 기록, 로그인 경로 검증(형식 밖 URL 거부·토큰 없음 503·gbrain 오류 502), 게이트 쿠키 서명·만료·변조
- nginx 규칙: `/admin` 은 `auth_request` 필수, `/mcp` 프록시 없음(#204 에서 `= /mcp` 만 인증 필수로 공개), `/admin/auth/` 로그 끔
- 배포 후 실측: 상태·로그·재시작, 감시 항목 up, 로그인 버튼 > gbrain 대시보드 진입, 게이트 없이 `/admin/` 401

- 관리자 화면의 "연결 안내"(SPA 의 `/.well-known/gbrain` 조회, `credentials: omit`)는 게이트 쿠키가 실리지 않아 동작하지 않음
  > 새 무인증 노출을 만들지 않으려고 그대로 둠 (클라이언트·토큰 관리 화면은 정상)

## 6. #198 과 실제 운영의 차이 (이번에 고친 것 / 남긴 것)

- 고침: 설계의 "gbrain 원격 MCP 서버 운영 안 함" > 운영함 (이 문서)
- 고침: 팀 브레인 쓰기 맥의 접속 경로 (외부 TLS 5432 아님, SSH 터널 127.0.0.1:15433)
- 남김: 팀원 외부 접속 `ai.postgres.suhsaechan.kr:5432` 가 2026-11-22 실측에서 닫혀 있음 (#198 배포 직후엔 성공)
  - 공유기 포트 포워딩·DSM 설정 확인 필요 (코드 밖, 소유자 판단)
