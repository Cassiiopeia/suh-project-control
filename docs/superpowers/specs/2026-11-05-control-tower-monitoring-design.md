# SUH 관제소: 서비스 감시 · 디스코드 알림 · 공개 status 페이지 설계

- 작성일: 2026-11-05
- 대상 레포: `Cassiiopeia/suh-project-control` (`suh-ai-server/flask` + 신규 `control-tower-worker/`)

## 1. 왜 만드는가

2026-11-03 저녁 시놀로지 NAS가 죽었는데 다음 날까지 아무도 몰랐다. NAS 위에는 서비스 40여 개가 돌고 있고(아래 3장), 친구 서버에서 내 NAS로 옮기는 elum 이전 작업처럼 상태를 사람이 기억에 의존해 추적하는 일이 늘었다.

목표는 하나다. **내 서비스가 죽으면 몇 분 안에 디스코드로 안다.** 그 위에 일반 사용자가 보는 공개 status 페이지(status.claude.com 같은 형태)와, 프로젝트별로 골라 들을 수 있는 디스코드 관제 채널을 얹는다.

## 2. 목표 · 비목표 · 반목표

**목표**
- 서비스 다운/복구를 3분 안에 디스코드로 알린다. 복구 시 다운 시간을 함께 알린다.
- NAS가 죽거나 집 인터넷이 끊겨도 알림이 온다(집 밖 감시기).
- 프로젝트별 디스코드 카테고리·채널·역할. 초대받은 사람은 관심 프로젝트만 골라 본다.
- 공개 status 페이지 `status.suhsaechan.kr`: 서비스별 현재 상태, 90일 가동 막대, 장애 기록.
- 새 프로젝트·서비스 추가는 등록 파일 한 곳 수정으로 끝난다(채널·역할·감시·status 노출이 자동으로 따라온다).
- 앱이 직접 이벤트(신고 접수, 에러 급증, 배포 결과)를 보낼 수 있는 입구를 처음부터 둔다(2단계에서 앱 연결).

**비목표 (이번에 안 함)**
- 공유기 자체 고장 대응 이중화(외부 감시기가 "집 연결 끊김"을 알리는 것까지만).
- 서버 자동 복구(재시작 등). 알림까지만 한다.
- 로그 수집·APM(에러 급증은 앱이 이벤트로 보내는 방식, 2단계).
- 유료 Cloudflare 기능(Health Checks, Load Balancing).

**반목표 (기술적으로 돌아가도 실패로 본다)**
- 알림 폭탄: NAS 하나 죽었는데 서비스 40개 알림이 따로 온다.
- 감시기가 감시 대상(NAS)에 의존해서 같이 죽는다.
- 공개 페이지에 내부 정보(에러 내용, 신고 내용, 내부 IP, 관리 도구 주소)가 노출된다.
- 시크릿(봇 토큰, 웹훅 URL)이 레포나 로그에 남는다.

## 3. 현재 상태 (2026-11-05 조사)

**네트워크 경로**
- `suhsaechan.kr` DNS는 Cloudflare(무료 플랜). 레코드 51개, 전부 `suh-project.synology.me`(집 공인 IP) CNAME.
- 집 공유기 443 → NAS DSM 역방향 프록시 → 각 서비스. Windows SUH AI 서버의 nginx는 11435 포트라서 `ai.suhsaechan.kr`도 NAS 프록시를 거친다(추정, 1단계 첫 작업에서 DSM 규칙으로 확인).
- **따라서 NAS가 죽으면 밖에서는 Windows 서버(관제소)에도 접속할 수 없다.** 단, Windows 서버 자체는 살아 있고 밖으로 나가는 연결(디스코드, Cloudflare)은 된다. 설계는 이 점에 기댄다: 집 ↔ Cloudflare 통신은 전부 **집에서 밖으로 나가는 방향**으로만 한다.

**외부에서 1회 찔러 본 결과 (2026-11-05, GET `/`)**
- 200/3xx/401/403 응답: suhsaechan.kr, www, ai, bagel, chat, chrome, file, freemates, lab, mail, minio, mongo, nexus, note, palim, pgadmin, pickerpicker, qdrant, rabbitmq, romrom, s3, server, traefik, web, api.passql, api.pickerpicker, api.romrom, api.elum(404=루트 경로 없음), api.mapsy, api.hack-the-beat, ai.passql, api.bagel(500)
- 502: ai.mapsy, ai.tripgether, api.sejong-malsami, api.spacestudyship, api.tripgether, api.test.tripgether, romi, sejong-malsami
- 연결 실패: admin.romrom, ai.mapsee, api.mapsee, lab.beta
- `*.pr`(PR 미리보기 와일드카드)은 감시 대상 아님.
- 실패 중인 12개가 "종료된 프로젝트"인지 "죽어 있는 서비스"인지는 사용자 확인 필요(9장).

**레포 기반**
- Flask 관리자 서버(`suh-ai-server/flask`, Windows NSSM + waitress:5000, 앞단 nginx가 `X-API-Key` 검사).
- 백그라운드 폴러 패턴 존재(`SystemMetricsPoller`, `PalworldEventPoller` — daemon thread, 틱 예외 삼킴).
- PostgreSQL 감사로그 DB(`AUDIT_DATABASE_URL`)가 있으나 호스트 위치 미확인. NAS 위라면 감시 데이터를 여기 두면 안 된다 → 감시 데이터는 Windows 로컬 SQLite에 둔다(5.4).
- 알림 발송 코드 없음. 다른 서버 헬스체크 기능 없음.

## 4. 전체 구조

```
                         ┌──────────── Cloudflare (집 밖, 무료) ────────────┐
                         │  control-tower-worker                              │
  일반 사용자 ──────────▶│   · status.suhsaechan.kr 공개 페이지 (D1에서 읽음)  │
                         │   · 1분 크론: 공개 주소 외부 점검 → D1 기록          │
                         │   · 관제소 심박 감시: 3분 끊기면 디스코드 긴급 웹훅   │
                         └──────────▲───────────────────────┬───────────────────┘
               심박+결과 수신(집→밖) │                       │ 긴급 알림(관제소 죽었을 때만)
                                    │                       ▼
┌──── 집 (Windows SUH AI 서버) ─────┴──────┐        ┌──────── Discord ────────┐
│  관제소 (Flask control_tower 모듈)        │ 봇API  │ SUH 관제소 서버           │
│   · 등록 파일(서비스·채널·노출) 단일 원본  │──────▶│  #관제-긴급 #관제-요약     │
│   · 1분 내부 점검(LAN: NAS, 도커, 로컬)   │        │  [elum] #상태 #에러 #신고 #배포│
│   · 외부 결과 병합 → 상태 판정 → 알림     │        │  [romrom] ...             │
│   · 이벤트 입구 POST /control/events      │        │  역할 = 프로젝트 구독       │
│   · 디스코드 채널·역할 자동 생성(동기화)  │        └──────────────────────────┘
│   · 관리자 화면 /admin/control            │
│   · SQLite (로컬 디스크)                  │
└──────────────────────────────────────────┘
        ▲ 앱 이벤트(2단계: elum 신고·에러 급증·배포)
```

역할 분담 원칙
- **관제소가 두뇌**: 상태 판정, 알림 문구, 채널 라우팅, 중복 억제는 모두 관제소 한 곳에서 한다.
- **Worker는 눈과 비상벨**: 밖에서 본 결과를 쌓아 두고, 관제소가 1분마다 심박을 보낼 때 응답으로 돌려준다. 관제소 심박이 끊길 때만 Worker가 직접 디스코드에 알린다.
- **공개 페이지는 Worker가 서빙**: 집이 통째로 죽어도 status 페이지는 떠 있어야 "지금 장애 중"을 보여 줄 수 있다.

## 5. 구성 요소

### 5.1 등록 파일 (단일 원본)

`suh-ai-server/flask/config/control_tower/services.yml` (레포 커밋, 시크릿 없음). 예시:

```yaml
projects:
  - id: elum                      # 디스코드 카테고리·역할 키
    name: 이룸
    discord:
      channels: [status, error, report, deploy]   # 쓰는 종류만
    services:
      - id: elum-api
        name: 이룸 API
        public: true              # status 페이지 노출
        depends_on: nas           # 부모가 죽으면 이 알림은 묶어서 억제
        checks:
          external: {url: https://api.elum.suhsaechan.kr/healthz, expect: [200]}
          internal: {url: http://<NAS LAN IP>:8079/healthz, expect: [200]}
infrastructure:                   # 다른 서비스의 부모
  - id: nas
    name: 시놀로지 NAS
    checks:
      internal: {tcp: <NAS LAN IP>:5001}
  - id: home-network
    name: 집 인터넷
    # 별도 점검 없음: Worker가 관제소 심박 끊김으로 판정
maintenance: []                   # [{service: elum-api, until: 2026-11-06T03:00+09:00, reason: 이전 작업}]
```

- 내부 IP·관리 도구(pgadmin, mongo, rabbitmq 등)는 `public: false`가 기본. 공개 여부는 등록 파일에서만 바꾼다.
- 등록 파일 변경 → 배포 → 관제소 기동 시 디스코드 동기화 + Worker에 설정 스냅샷 전달(공개 필드만).

### 5.2 상태 판정과 알림 규칙

- 점검 간격 60초. 상태: `up` / `degraded`(느림 > 5초 또는 기대 외 응답) / `down`.
- **정상 판정 기준(1단계)**: 앱에 `/healthz`를 새로 만들지 않는다(다른 레포 수정으로 범위가 커지므로). 서비스마다 등록 파일의 `expect`에 정상 응답 코드를 적는다. 기본값은 "HTTP 응답이 오고 502·503·504가 아니면 정상"이다. 즉 401·403·404도 앱이 살아 있다는 뜻으로 본다. 연결 실패, TLS 실패, 타임아웃, 502·503·504는 실패로 본다. 이미 `/healthz`가 있는 서비스(elum)는 그 경로를 쓴다. `/healthz` 추가는 2단계에서 앱별로 한다.
- 등록 파일의 서비스 상태값: `active`(감시·알림·공개) / `paused`(감시만, 알림·공개 없음) / `retired`(감시 안 함, 기록 보존).
- **3회 연속 실패 → down 알림**, **2회 연속 성공 → 복구 알림**(다운 시간 포함). down 지속 중에는 6시간마다 1회 재알림.
- 외부·내부 결과를 합쳐 원인을 나눈다: 내부 OK + 외부 실패 = "바깥 연결 문제(프록시/포트포워딩/DNS)", 둘 다 실패 = "서비스 다운".
- **부모 억제**: `depends_on` 부모(nas, home-network)가 down이면 자식 알림을 보내지 않고 부모 알림 1건에 "영향 서비스 N개" 목록으로 묶는다.
- **점검 중(maintenance)**: 기간 동안 알림 대신 "점검 중"으로 표시. 관리자 화면·(3단계) 슬래시 명령으로 켠다. "서버 닫고 업데이트" 상황용.
- 하루 1회(09:00 KST) `#관제-요약`에 전날 가동률·장애 요약.

### 5.3 이벤트 입구 (2단계 앱 연결의 기반)

`POST /control/events` — 프로젝트별 토큰(`X-Control-Token`)으로 인증.

```json
{"project": "elum", "kind": "report|error|deploy|status|info",
 "severity": "info|warning|critical", "title": "...", "body": "...",
 "dedupe_key": "report-123", "url": "https://..."}
```

- 관제소가 `kind`로 채널을 고르고, `dedupe_key`로 10분 내 중복을 묶는다.
- 1단계에서는 입구와 라우팅까지만 만들고 관제소 내부 알림(상태)이 이 경로를 그대로 쓴다. 앱 연결은 2단계.
- 공개 경로 노출: nginx의 `X-API-Key` 검사 대상에서 이 경로만 제외하고 토큰으로 인증(앱이 관리자 키를 갖지 않게).
- 실제 주소: nginx가 `/api/flask/` 아래만 Flask로 넘기므로 외부 주소는 `https://ai.suhsaechan.kr/api/flask/control/events`, 관리자 화면은 `/api/flask/admin/control`이다(문서의 짧은 경로는 Flask 내부 경로). nginx 예외 규칙은 `suh-ai-server/config/nginx.conf`에 이 경로 하나만 추가한다.

### 5.4 저장소

- 관제소: Windows 로컬 SQLite(`flask/data/control_tower.db`, gitignore). 테이블: `check_result`(원시, 7일 보관), `daily_rollup`(90일+), `incident`(상태 변화 구간), `event_log`(30일), `discord_binding`(프로젝트·종류 → 채널 ID).
- Worker: D1(무료 하루 10만 행 쓰기). 크론 1회당 1행(전체 결과 JSON) = 하루 1,440행, 일별 집계는 자정 이후 1회. 설정 스냅샷은 KV.

### 5.5 Cloudflare Worker (`control-tower-worker/`, 레포 신규 폴더)

- `scheduled` (1분): 등록 파일 스냅샷의 `external` 점검 실행 → D1 기록. 관제소 마지막 심박이 3분 넘게 없으면 디스코드 `#관제-긴급` 웹훅으로 "관제소/집 연결 끊김"(복구 시 1회 더).
- `POST /heartbeat` (HMAC 서명): 관제소가 1분마다 호출. 응답으로 최근 외부 점검 결과를 돌려준다. 설정 스냅샷 갱신도 이 호출에 싣는다.
- `GET /` (status.suhsaechan.kr): 공개 서비스만, 프로젝트별 묶음, 현재 상태, 90일 막대, 최근 장애, 마지막 갱신 시각. 서버 렌더링 HTML 한 장(외부 프레임워크 없음).
- 무료 한도 주의: 크론 실행당 CPU 10ms(대기 시간 제외), 실행당 외부 요청 수 제한이 있다. 외부 점검 대상은 `external`이 있는 서비스로 한정하고, 수가 많으면 크론 2개로 나눈다(무료 5개까지). 첫 배포 때 실측.
- 배포: wrangler, GitHub Actions(main 머지 시). Cloudflare API 토큰은 Workers·D1·해당 존 Workers Routes 권한만.

### 5.6 디스코드

- 새 디스코드 서버 "SUH 관제소"(사용자 계정 chan4760 소유) + 봇 애플리케이션 1개. 웹훅 여러 개 대신 **봇 토큰 1개**로 모든 채널에 보낸다(채널 추가가 설정만으로 끝남). Worker 비상용으로만 웹훅 1개.
- 구조: 상단 `#공지` `#관제-긴급` `#관제-요약` / 프로젝트마다 카테고리 + 등록 파일의 `channels` 종류별 채널 / 프로젝트마다 역할.
- **동기화**: 관제소가 등록 파일 기준으로 카테고리·채널·역할을 없으면 만들고, 이름이 바뀌면 고친다. 삭제는 하지 않는다(보관 카테고리로 이동만). 관리자 화면 버튼 + 기동 시 1회.
- **골라 듣기**: 디스코드 기본 기능 "온보딩"에서 "어떤 프로젝트 알림을 받을까요?" 질문 → 프로젝트 역할 부여 → 해당 카테고리만 보임. 관리자 역할은 전부 보임. 온보딩 질문 목록도 동기화 대상(API로 가능하면 자동, 아니면 첫 설정 때 수동 1회).
  - 온보딩은 커뮤니티 서버에서만 되므로 서버를 커뮤니티로 전환한다(규칙 채널·인증 수준 설정 포함). 무료이고 이 용도에 부작용이 없다.
- **권한 단계 (프로젝트마다 역할 2개)**:
  - `<프로젝트>` 역할: 온보딩에서 고를 수 있다. `#상태`, `#배포`만 보인다.
  - `<프로젝트>-dev` 역할: 관리자가 직접 준다. `#에러`, `#신고`까지 보인다. 신고 내용과 에러 내용은 여기에만 올라간다.
  - `관리자` 역할: 본인. 모든 채널이 보이고, `#관제-긴급`, `#관제-요약`은 관리자만 본다. 인프라 정보가 들어가기 때문이다.
  - `#공지`는 모두에게 보인다.
- **수동 준비 단계**(사용자 계정 필요, 빌더가 pro-launch 브라우저로 진행): 디스코드 서버 생성, 커뮤니티 전환, 봇 애플리케이션 등록과 토큰 발급, 봇 초대, `#관제-긴급` 비상 웹훅 발급. 디스코드는 새 IP 로그인 때 메일 확인 코드가 올 수 있다. 사용자가 이 작업을 빌더에게 맡겼다.
- 알림 메시지: 임베드(색: 빨강 down, 초록 복구, 노랑 degraded), 서비스명, 원인 분류, 시작 시각, 영향 서비스, status 페이지 링크.

### 5.7 관리자 화면 `/admin/control`

기존 관리자 레이아웃 재사용. 서비스 격자(현재 상태·마지막 점검·내부/외부 결과), 진행 중 장애, 최근 이벤트, 점검 중 설정, "디스코드 동기화"·"테스트 알림" 버튼. 등록 파일 편집은 하지 않는다(레포가 원본).

## 6. 시크릿과 설정 위치

| 값 | 위치 |
|---|---|
| `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID` | Flask `.env` (CICD가 GitHub Secret `FLASK_ENV_FILE` 한 덩어리로 생성 → 새 키 추가 시 이 Secret 전체를 갱신) |
| `CONTROL_TOWER_HMAC_SECRET` | Flask `.env` + Worker secret (같은 값) |
| 프로젝트별 이벤트 토큰 | Flask `.env` (`CONTROL_EVENT_TOKEN_<PROJECT>`) |
| 비상 디스코드 웹훅 URL | Worker secret만 |
| Cloudflare API 토큰 | GitHub Secret (Worker 배포용) |

## 7. 단계

1. **1단계 (이번 이슈)**: 등록 파일, 관제소 점검·판정·알림·SQLite·이벤트 입구, 디스코드 서버·봇·동기화, Worker(외부 점검·심박 감시·status 페이지), `status.suhsaechan.kr` 연결, 관리자 화면. 완료 기준: NAS 서비스 하나를 멈추면 3분 안에 해당 프로젝트 `#상태`에, Windows 서버 Flask를 멈추면 4분 안에 `#관제-긴급`에 알림이 오고, 재기동 시 복구 알림이 온다.
2. **2단계**: elum부터 앱이 신고·에러 급증·배포 이벤트를 보내도록 연결. 배포 워크플로에 결과 알림 스텝 추가.
3. **3단계**: 슬래시 명령(`/status`, `/ack`, `/maintenance`) — 디스코드 상호작용 엔드포인트를 Worker에 둔다(집이 죽어도 응답). 관리자 역할만 실행.

## 8. 빌더에게 맡기는 것

- 모듈·파일 분할, SQLite 스키마 세부, 임베드 문구 세부, status 페이지 디자인(기존 관리자 화면 색과 맞추는 선에서), 재시도·타임아웃 수치(점검 타임아웃 기본 10초), 테스트 구성.

## 9. 사용자 확인이 필요한 것

- **실패 중인 12개 서비스의 처리**(3장 목록): 종료된 프로젝트인지, 살아 있어야 하는데 죽은 건지. 답이 오기 전 기본값은 `status: paused`(점검은 하되 알림·공개 노출 안 함, 관리자 화면에 "확인 필요"로 표시). 답에 따라 등록 파일에서 삭제하거나 `active`로 바꾼다. 1단계 진행을 막지 않는다.

## 9-1. 1단계 시작 전 실측 확인 (빌더가 먼저 할 일)

설계의 전제를 깨는 사실이 있는지 코드 작성 전에 확인한다. 어긋나면 해당 절을 고치고 진행한다.

1. **NAS 의존성**: Windows 서버의 DNS·기본 게이트웨이·DHCP가 NAS에 걸려 있는지(`ipconfig /all`, 읽기 전용 SSH). NAS가 DNS를 맡고 있으면 Windows의 DNS를 공유기 또는 공용 DNS(1.1.1.1, 8.8.8.8)로 바꾸는 작업을 1단계에 추가한다(사용자 승인 후). 그래야 NAS 장애 때도 관제소가 밖으로 알림을 보낼 수 있다.
2. **서비스 위치 목록**: NAS DSM 역방향 프록시 규칙(`synowebapi` list, 읽기 전용)과 Windows nginx 설정으로 "도메인 → 실제 호스트:포트" 표를 만든다. 이 표로 등록 파일의 `internal` 점검 주소와 `depends_on` 부모(nas / windows / 기타 호스트)를 채운다. NAS 밖에서 도는 서비스는 nas에 묶지 않는다.
3. **ai.suhsaechan.kr 경로**: 2번 결과로 NAS 프록시 경유 여부를 확정한다.
4. **감사 DB 위치**: `AUDIT_DATABASE_URL` 호스트가 어디인지(값 출력 금지, 호스트만). 5.4의 SQLite 결정은 그대로 두되 기록해 둔다.

## 10. 판단 기록 (사용자 미확인, 설계자 판단)

- 감시 본체를 Flask 관제소 + Cloudflare Worker 둘로 나눔(사용자는 "Worker 방향 좋다", "관제소는 ai 서버 내부" 둘 다 원함 → 역할 분리로 조합).
- 집↔Cloudflare 통신을 집→밖 방향만 사용(NAS가 죽으면 밖에서 관제소에 못 들어오므로).
- 감시 데이터는 PostgreSQL이 아닌 로컬 SQLite(감사 DB가 NAS에 있을 가능성 대비).
- 웹훅 여러 개 대신 봇 토큰 1개.
- 등록 파일은 레포 YAML(관리자 화면 편집 없음).
- 알림 기준 3회 연속 실패, 재알림 6시간, 일일 요약 09:00.
- 1단계는 `/healthz`를 만들지 않고 기존 응답 코드로 판정(502·503·504·연결 실패만 실패).
- 프로젝트 묶음은 서브도메인 이름 기준(예: `api.romrom`, `admin.romrom`, `romrom` → romrom)으로 초안을 만들고, 관리 도구(mongo, pgadmin, rabbitmq, minio, qdrant, nexus, traefik, s3, server)는 `infra` 프로젝트로 모아 비공개.
- 디스코드 커뮤니티 서버 전환, 프로젝트별 역할 2단계(`<프로젝트>` / `<프로젝트>-dev`), 관제 채널은 관리자 전용.
- 실패 중인 12개는 `paused`로 시작.
