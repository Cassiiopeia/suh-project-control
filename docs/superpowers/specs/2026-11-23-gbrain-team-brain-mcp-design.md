# gbrain 팀 브레인 MCP 설계 (프로젝트별 gbrain 서버, 읽기 전용 팀원 토큰)

- 작성: 2026-11-23
- 이슈: Cassiiopeia/suh-project-control#210
- 앞 문서: [팀 브레인 DB·권한](2026-11-19-gbrain-team-brain-design.md) (#198), [gbrain HTTP 서버](2026-11-22-gbrain-http-server-control-tower-design.md) (#201),
  [공개 MCP](2026-11-22-gbrain-public-mcp-design.md) (#204), [MCP 토큰 관리](2026-11-22-gbrain-token-management-design.md) (#207)

## 1. 왜

#198 의 팀원 접속 경로(외부 Postgres `ai.postgres.suhsaechan.kr:5432` 직접 마운트)는 공유기에서 닫혀 있어 쓸 수 없다.
DB 를 다시 여는 대신, #201~#207 에서 개인 브레인에 쓴 방식(gbrain HTTP 서버 + 공개 `/mcp` + 기기 토큰)을 **팀 브레인마다 하나씩** 둔다.
팀원은 Claude Code 에 MCP 서버를 하나 더할 뿐이고, 개인 gbrain 은 그대로 둔다.

## 2. 목표 / 하지 않는 것 / 실패로 보는 것

- 목표
  - 팀 브레인마다 gbrain HTTP 서버 1개: NSSM `gbrain-team-<project>`, 자기 `GBRAIN_HOME`, 자기 내부 포트, 자기 DB 만 봄
  - 공개 주소 `https://ai.suhsaechan.kr/team/<project>/mcp`, `/mcp` 와 같은 바깥 필터
  - 토큰 카드에서 브레인을 골라 발급·폐기 (팀 기본 읽기 전용), 연결 한 줄은 MCP 이름 `gbrain-<project>`
  - "팀 브레인 만들기": DB·쓰기 계정·브레인 준비·설정·서비스·공개 경로·감시를 한 번에, 다시 눌러도 같은 결과
  - passQL 을 이 흐름으로 옮김 (DB 그대로, 데이터 손실 없음)
- 하지 않는 것
  - Postgres·Ollama·gbrain `/admin` 새 공개 (팀 브레인 `/admin`·OAuth·discovery 도 공개 안 함)
  - 서버 쪽 `knowledge/` 동기화: 지금처럼 쓰기 계정을 가진 동기화 맥 1대가 맡음
  - 팀원 개인 gbrain 설정 변경 (안내도 건드리지 않음)
- 실패로 보는 것
  - 읽기 전용 토큰으로 쓰기(`remember` 등)가 됨
  - 팀 브레인 작업이 개인 브레인(`gbrain-http`, DB `gbrain`, `/mcp`)이나 그 데이터에 영향을 줌
  - 개인 내용이 팀 브레인에 들어감 (팀 브레인 원본은 프로젝트 레포 `knowledge/` 뿐)

## 3. 구조

```
팀원 Claude ── https://ai.suhsaechan.kr/team/passql/mcp (Bearer 팀원 토큰, MCP 이름 gbrain-passql)
  > Cloudflare > NAS 프록시 > nginx 11435
      location ~ ^/team/(?<team_brain_project>[a-z][a-z0-9]+)/mcp$
        1) POST 아니면 405  2) Bearer 형식 아니면 401  3) map 에 없는 프로젝트 404
        4) /mcp 와 같은 속도 제한 2개(429)·본문 4MB·로그 형식 mcp(토큰 없음)·CORS * 미상속
      proxy_pass http://$team_brain_upstream/mcp   (map: C:/AI/gbrain/teams/nginx/<project>.map = "passql 127.0.0.1:3141;")
  > gbrain-team-passql (NSSM, 127.0.0.1:3141, GBRAIN_HOME C:\AI\gbrain\teams\passql)
      ├─ Postgres gbrain-postgres 127.0.0.1:5433 / gbrain_passql (쓰기 계정 passql_writer)
      └─ Ollama 127.0.0.1:11434 (개인 브레인과 같은 임베딩 모델)

동기화 맥 ── SSH 터널 127.0.0.1:15433 ── passql_writer ── gbrain_passql   (~/gbrains/passql/sync.sh, knowledge/ 만)
개인 Claude ── https://ai.suhsaechan.kr/mcp ── gbrain-http 127.0.0.1:3131 / DB gbrain   (변경 없음)
```

### 경로 접두사 판단

- gbrain 은 `/mcp` 만 알지만 nginx 가 `proxy_pass http://$team_brain_upstream/mcp` 로 경로를 통째로 바꿔 보냄 > gbrain 은 접두사를 모름
- 상태 없는 전송(세션 URL·SSE 역채널 없음, #204) 이라 응답에 주소가 실리지 않음 > 접두사 뒤에서도 그대로 동작 (배포 후 실측 9장)
- Claude Code 는 고정 Bearer 헤더를 보내므로 OAuth discovery(`/.well-known/...`)를 찾지 않음
- 포트는 nginx 변수 하나로 고르고, map 파일은 배포 폴더 밖이라 배포가 팀 브레인을 지우지 않음. 파일이 0개여도 `nginx -t` 통과 (실측)

### 읽기 전용 판단 (gbrain 0.60.739.0 소스)

- `remember` 는 `scope: 'write'` (src/core/ops/memory-settings.ts), HTTP 호출은 `operationScopesAllowed(auth.scopes, op)` 로 검사 (src/mcp/dispatch.ts)
- 토큰 `scopes = ['read']` 이면 쓰기 동작은 `insufficient_scope` 로 거부 (배포 후 실측 9장)
- 서비스의 DB 계정은 쓰기 계정이지만(토큰 표·세션도 그 DB 에 씀) 쓰기 권한은 토큰 범위가 막음

### 이름 규칙 (프로젝트 키 하나로 전부 정해짐)

| 대상 | 값 (passQL) |
|---|---|
| 프로젝트 키 | `passql` (`^[a-z][a-z0-9]{1,19}$`, `personal` 금지) |
| DB / 쓰기 계정 | `gbrain_passql` / `passql_writer` |
| NSSM 서비스 / 내부 포트 | `gbrain-team-passql` / `3141` (3141~3199 중 빈 가장 작은 값, 등록부에 고정) |
| GBRAIN_HOME / 설정 | `C:\AI\gbrain\teams\passql` / `...\passql\.gbrain\config.json` (SYSTEM·Administrators 만) |
| 관리자 토큰 / 로그 | `C:\AI\secrets\gbrain-team-passql-admin-token` / `C:\AI\gbrain\teams\passql\logs\gbrain-http.log` |
| 공개 주소 / MCP 이름 | `https://ai.suhsaechan.kr/team/passql/mcp` / `gbrain-passql` |
| 등록부 / nginx map | `C:\AI\gbrain\teams\team-brains.json` / `C:\AI\gbrain\teams\nginx\passql.map` |

## 4. 만들기 흐름 (`POST /gbrain/teams`, 감사 `GBRAIN_TEAM_CREATE`)

| 단계 | 하는 일 | 다시 누르면 |
|---|---|---|
| database | `gbrain_<key>` 없으면 생성 (AiDbService) | kept |
| writer_role | `<key>_writer` 없으면 생성 + 접속 권한, 새 비번은 응답 1회 | kept (비번 재설정 안 함: 동기화 맥이 끊기지 않게) |
| prepare | `ai_db_ops.prepare_gbrain_database` (이미 준비됐고 쓰기 계정 같으면 건너뜀) | kept |
| 등록 | 등록부에 프로젝트·포트·DB·계정 (비번 없음) | 같은 포트 |
| admin_token | 브레인 전용 관리자 토큰 파일 (없을 때만) | kept |
| config | 스키마 있는 DB: 설정 파일 쓰기 + `gbrain init --migrate-only` / 빈 DB: `gbrain init --url ... --non-interactive` | 설정 있고 새 비번 없으면 kept |
| service | `setup-gbrain-http.ps1 -SkipInstall -ServiceName ... -Port ... -GbrainHome ... -BunHome ...` > `/health` | 서비스 갱신·재기동 |
| nginx | map 파일 쓰기 > `nginx -t` > reload (실패하면 이전 내용 복원) | 같은 내용이면 kept |
| monitoring | `gbrain-team-brains` 감시(Flask `/gbrain/teams/health`)에 자동 포함 | - |

- 기존 쓰기 계정 + 서버 설정 없음 > 409 `writer_password_required` (화면 "기존 쓰기 계정 비밀번호" 칸에 동기화 맥의 비번)
- 새 계정을 만든 뒤 뒤 단계가 실패해도 오류 응답에 `writer_secret` 을 1번 실음 (다시 받을 방법이 없음)
- 개인 브레인 설정에서 옮기는 값: `embedding_model`·`embedding_dimensions`·`schema_pack` 만 (`memory.auto_writeback` 같은 개인 기억 설정은 안 옮김)
- gbrain 명령은 `GBRAIN_HOME`·`HOME`·`USERPROFILE` 을 팀 폴더로 고정 > 개인 `C:\Users\kimchi\.gbrain` 을 건드리지 않음
- 응답 `Cache-Control: no-store`, 감사 상세는 프로젝트·단계·포트·비번 입력 여부만, 명령 실패 사유는 `postgresql://계정:***@` 로 가림
- 브라우저 경로는 Cloudflare 100초 제한이 있어 오래 걸리면 524 가 보일 수 있음 > 다시 누르면 이어서 함

## 5. API (nginx `X-API-Key`, 감시만 127.0.0.1:5000 직접)

| 메서드 | 경로 | 하는 일 |
|---|---|---|
| GET | `/gbrain/teams` | 팀 브레인 목록 + 서비스 상태·헬스·주소·MCP 이름·포트·DB |
| POST | `/gbrain/teams` | 만들기 `{project, writer_password?}` (`GBRAIN_TEAM_CREATE`) |
| GET | `/gbrain/teams/health` | 전부 정상 200, 하나라도 응답 없음 503 (`gbrain-team-brains` 감시) |
| GET | `/gbrain/teams/<project>/status`·`/logs` | 한 브레인 상태·로그 끝 N줄 |
| POST | `/gbrain/teams/<project>/control/<start\|stop\|restart>` | 제어 (`GBRAIN_START/STOP/RESTART`, 상세 brain) |
| GET·POST | `/gbrain/tokens?brain=` · 본문 `brain` | #207 토큰 API 에 브레인 선택 추가 (없으면 개인), 응답 `mcp_server_name`·`default_scope_preset` |

## 6. 공존 규칙 (팀원 개인 gbrain 과 충돌 없음)

1. **이름**: 팀 서버는 항상 `gbrain-<project>` 로 추가. Claude 는 서버 이름으로 도구를 나눔 (`mcp__gbrain__recall` ↔ `mcp__gbrain-passql__recall`)
   - 개인 `gbrain` 이 HTTP 든 로컬 stdio(`gbrain serve`) 든 이름이 달라 같이 연결됨 (배포 후 실측 9장)
2. **설정**: 안내는 `claude mcp add ... gbrain-<project>` 한 줄뿐. 개인 gbrain 설정·훅(SessionStart·UserPromptSubmit)·`~/.gbrain`·mounts·sources·토큰은 바뀌지 않음
3. **데이터**: 팀 브레인 = 자기 DB + 자기 서비스 + 자기 토큰. 원본은 프로젝트 레포 `knowledge/` 뿐, 개인 내용은 동기화하지 않음
   - 팀원의 개인 훅이 팀 브레인에 쓰지 않음: 개인 훅은 개인 gbrain 에만 붙고, 팀 토큰은 읽기 전용
4. **mounts 방식(선택)**: 마운트 id 는 `team-<project>`, 이미 같은 id 가 있으면 gbrain 이 `Mount id already exists` 로 거부 (덮어쓰지 않음, 실측)

## 7. 팀원 연결 안내 (토큰 결과 창 "팀원에게 보낼 안내" 와 같은 내용)

### 방법 1 (권장): MCP 서버 하나 더하기

```bash
claude mcp add --scope user --transport http gbrain-passql https://ai.suhsaechan.kr/team/passql/mcp \
  --header "Authorization: Bearer <관리자가 1:1 로 준 토큰>"
# Claude Code 다시 열기 > /mcp 에서 gbrain-passql connected 확인
```

- 이미 `gbrain-passql` 이 있다고 나오면 `claude mcp remove gbrain-passql -s user` 후 다시
- 개인 `gbrain` 이 있어도 그대로 둠. 둘 다 connected 로 보임

### 방법 2: gbrain 을 직접 쓰는 사람의 mounts (로컬 사본)

- gbrain 0.60.739.0 의 `mounts` 는 DB 직접 연결(pglite·postgres)만 지원. HTTP 마운트(`--mcp-url`)는 아직 구현 안 됨 (src/commands/mounts.ts "NOT YET IMPLEMENTED")
- 팀 DB 는 공개하지 않으므로, 마운트하려면 레포 `knowledge/` 를 **자기 컴퓨터의 별도 PGLite 브레인**으로 동기화해 그걸 마운트함 (팀 서버 불필요, 읽기 전용 사본)

```bash
# 0) 이름 겹침 확인 (있으면 멈추고 다른 id 를 쓰거나 기존 것을 직접 정리)
gbrain mounts list | grep -q 'team-passql' && echo "team-passql 마운트가 이미 있어요" && exit 1
# 1) knowledge/ 만 받기
git clone --filter=blob:none --sparse https://github.com/<owner>/passQL ~/gbrains/team-passql/repo
git -C ~/gbrains/team-passql/repo sparse-checkout set knowledge
# 2) 별도 브레인 (GBRAIN_HOME 을 이 줄들에만 붙여 개인 ~/.gbrain 과 분리)
GBRAIN_HOME=~/gbrains/team-passql gbrain init --pglite --non-interactive
GBRAIN_HOME=~/gbrains/team-passql gbrain sources add passql-knowledge --path ~/gbrains/team-passql/repo
GBRAIN_HOME=~/gbrains/team-passql gbrain sync --source passql-knowledge
# 3) 개인 브레인에 마운트 (mounts.json 에 team-passql 1줄만 추가)
gbrain mounts add team-passql --path ~/gbrains/team-passql --engine pglite \
  --db-path ~/gbrains/team-passql/.gbrain/brain.pglite
# 갱신: git -C ~/gbrains/team-passql/repo pull && GBRAIN_HOME=~/gbrains/team-passql gbrain sync --source passql-knowledge
```

- `/tmp` 아래처럼 심볼릭 링크가 낀 경로는 content root 경고가 남 > 홈 아래 실제 폴더 사용
- 의미 검색(임베딩)은 각자 임베딩 설정을 따름. 없으면 키워드 검색만

## 8. 운영 런북

### 새 프로젝트 팀 브레인 만들기 (관제소)

1. 관제소 > gbrain 서버 > "팀 브레인" 카드 > **팀 브레인 만들기** > 프로젝트 키 (예: `romrom`) > 만들기
2. 결과 창의 **동기화 맥 연결 문자열**을 복사 (1번만 보임) > 동기화 맥에 팀 브레인 폴더 준비
   ```bash
   mkdir -p ~/gbrains/romrom && cd ~/gbrains/romrom
   git clone --filter=blob:none --sparse https://github.com/<owner>/<repo> repo && git -C repo sparse-checkout set knowledge
   GBRAIN_HOME=~/gbrains/romrom gbrain init --url '<결과 창 연결 문자열>' --non-interactive
   GBRAIN_HOME=~/gbrains/romrom gbrain sources add romrom-knowledge --path ~/gbrains/romrom/repo
   ```
   그리고 `~/gbrains/passql/sync.sh` 를 복사해 프로젝트 이름만 바꾸고 1시간 주기로 등록 (passQL 과 같은 방식)
3. 토큰 카드 > 브레인 `romrom 팀 (gbrain-romrom)` 선택 > **새 기기 연결** > 팀원 이름 (예: `kim-macbook`), 권한 읽기 전용 > 결과 창 "팀원에게 보낼 안내"를 그 팀원에게 1:1 로 전달
4. 관제소 상태: "gbrain 팀 브레인 전체" 감시가 up 인지 확인 (프로젝트별 감시가 필요하면 `services.yml` 에 `internal: http://127.0.0.1:<포트>/health` 추가)
5. 팀원이 빠지면 그 토큰만 폐기

### 다른 팀이 자기 서버에 직접 구축할 때

레포 `knowledge/` 폴더는 특정 gbrain 에 묶이지 않음: 어떤 gbrain 이든 `gbrain sync` 로 넣을 수 있음. 최소 명령:

```bash
# 1) 팀 브레인 전용 폴더·DB (개인 ~/.gbrain 과 분리: GBRAIN_HOME 을 따로)
export GBRAIN_HOME=/srv/gbrain/<project>
gbrain init --url 'postgresql://<writer>:<pw>@<db-host>:5432/gbrain_<project>' --non-interactive   # 또는 --pglite
# 2) knowledge/ 동기화 (주기 실행: git pull + sync)
git clone --filter=blob:none --sparse <repo-url> $GBRAIN_HOME/repo && git -C $GBRAIN_HOME/repo sparse-checkout set knowledge
gbrain sources add <project>-knowledge --path $GBRAIN_HOME/repo
gbrain sync --source <project>-knowledge && gbrain extract --stale --catch-up --source-id <project>-knowledge
# 3) HTTP MCP 로 공유 (127.0.0.1 에만 띄우고 앞단 리버스 프록시에서 TLS·Bearer·속도 제한)
gbrain serve --http --bind 127.0.0.1 --port 3141
gbrain auth create <teammate> --scopes read        # 팀원 토큰 (원문은 1번만 출력)
# 4) 팀원: claude mcp add --scope user --transport http gbrain-<project> https://<host>/<path>/mcp --header "Authorization: Bearer <토큰>"
```

- 앞단 프록시 규칙은 이 레포 `suh-ai-server/config/nginx.conf` 의 `location ~ ^/team/...` 블록을 그대로 참고 (POST·Bearer 필수, 속도 제한, `/admin`·OAuth 비공개)

## 9. 시험

- 단위: 이름 규칙·등록부(포트 배정·유지·손상 감지), 만들기 흐름(새 프로젝트·passQL·다시 만들기·비번 요구·중간 실패 시 비번 전달·AI DB 오류 전달), 서버 작업(토큰 유지·임베딩 값만 복사·팀 폴더 고정·비번 가림·nginx 검사 실패 복원), 라우터(no-store·감사 비번 없음·헬스 200/503·제어·토큰 브레인 선택·팀 기본 읽기 전용), nginx 규칙(경로 모양·검사 순서·속도·로그·비공개)
- 배포 후 실측: passQL 서비스 정상 > 시험 읽기 토큰 > 팀 주소 initialize 200 > 검색에 passQL 지식 > 쓰기 거부 > 폐기 > 401, 개인 `/mcp` 200, 로그·감사에 토큰 없음, 임시 Claude 설정에서 `gbrain`(HTTP·stdio) + `gbrain-passql` 동시 connected
