# 관제소 2단계: 서비스 관리 화면 · status 페이지 브랜딩 · SEO (#159)

## 왜
- 감시 대상·이름·공개 여부를 바꾸려면 레포의 `services.yml`을 고치고 배포해야 함. 소유자는 관리자 화면(ai.suhsaechan.kr)에서 전부 바꾸고 싶어 함.
- Cloudflare DNS에 쓰지 않는 도메인이 섞여 있음. 추적할 것과 안 할 것을 화면에서 고르고, 새 도메인은 DNS에서 가져와야 함.
- 공개 페이지가 밋밋함. 브랜드(SUHSAECHAN Status, Twin-Fang 로고)와 SEO가 없음.

## 결정 (소유자 확정)
- 사이트 이름 기본값 **SUHSAECHAN Status**. 검색 설명과 JSON-LD `alternateName`에 **Cassiiopeia Status**도 넣음. 관리자 화면에서 바꿀 수 있음.
- 로고: `brand/twin-fang-logo.jpg` (Twin-Fang 팀 로고, 256px, 어두운 바탕 주황 발톱 두 줄). 원본은 이 파일 하나. 플랫폼 사본은 스크립트로 생성.
- 화면에서 고친 값은 **Flask SQLite에 저장**하고 등록 파일 위에 덮어씀. 재배포하면 등록 파일은 레포 내용으로 덮이므로 DB가 유일하게 살아남는 곳임. `services.yml`은 기본값과 처음 목록임.

## 계약 1: 덮어쓰기 저장소 (Flask SQLite, 새 테이블)
- `service_override(service_id PK, name, status, is_public, sort_order, external_url, updated_at)`
  - 모든 칸은 NULL 허용. NULL이면 등록 파일 값을 씀.
  - `status`: `active`=추적함 / `paused`=감시만(알림 없음) / `retired`=추적 안 함
- `custom_service(id PK, project_id, name, external_url, status, is_public, sort_order, created_at)`
  - 화면에서 추가한 서비스임. 등록 파일 id와 겹치면 거부함.
  - 삭제할 수 있음. 등록 파일 서비스는 삭제할 수 없고 `retired`만 가능함.
  - 외부 점검만 있음(`external_url`). 내부 점검은 등록 파일 서비스만 가짐.
  - `depends_on`은 `nas`를 기본으로 함.
- `project_override(project_id PK, name, is_hidden, sort_order, updated_at)`
  - 숨긴 프로젝트의 서비스는 공개 페이지에서 빠짐(스냅샷 `is_public` false). 감시와 알림은 그대로임.
- `custom_project(id PK, name, sort_order, created_at)`
- 상태 페이지 설정(meta 키)
  - `status_page_title`: 기본 "SUHSAECHAN Status"
  - `status_page_notice_text`: 300자 이하, 빈 문자열이면 공지 없음
  - `status_page_notice_level`: `info` | `warning` | `critical`
- 검증
  - id: `^[a-z0-9][a-z0-9-]{1,40}$`
  - 이름: 1~60자
  - URL: `https://` 또는 `http://`로 시작하고 2048자 이하
  - 실패하면 400과 사유를 돌려줌

## 계약 2: 실효 등록 정보 (Flask)
- 순서: `load_registry(파일)` > `apply_overrides(registry, store)` > 실효 `Registry`
- 폴러 재로드(`poller._reload_registry`), 기동 디스코드 동기화, 관리자 동기화가 모두 이 실효 등록 정보를 씀. 단일 원본 함수는 하나만 둠.
- 정렬: 프로젝트와 서비스 모두 `(sort_order NULL은 맨 뒤, 등록 파일 순서, id)`

## 계약 3: Worker 스냅샷 확장 (기존 필드 유지 + 추가)
```json
{"page": {"title": "SUHSAECHAN Status",
          "notice": {"text": "...", "level": "info"}},
 "projects": [{"id": "elum", "name": "elum", "order": 0}],
 "services": [{"id": "...", "order": 0, "...기존 필드": "..."}]}
```
- `notice`는 공지가 없으면 null임.
- `projects`와 `services`는 표시 순서대로 내보냄. Worker는 배열 순서를 그대로 씀(id 정렬 금지).
- `page`가 없는 옛 스냅샷이면 Worker는 기본값을 씀(제목 "SUHSAECHAN Status", 공지 없음).

## 계약 4: 관리 API (Flask, 기존 `/control/*`와 같은 블루프린트, nginx API 키 보호)
- `GET /control/manage`
  - 실효 프로젝트·서비스 목록과 원본·덮어쓰기 구분을 돌려줌. 서비스마다 `source`(`registry`|`custom`), 현재 상태, url, 덮어쓴 필드 목록을 담음. 페이지 설정도 함께 줌.
- `PATCH /control/services/<id>`
  - 받는 값: `{name?, status?, is_public?, sort_order?, external_url?}`
  - `null`을 보내면 그 필드의 덮어쓰기를 지움(등록 파일 값으로 되돌림).
- `POST /control/services`
  - 받는 값: `{id, project_id, name, external_url, status?, is_public?}`
  - 사용자 추가 서비스를 만듦.
- `DELETE /control/services/<id>`
  - 사용자 추가 서비스만 지울 수 있음. 등록 파일 서비스는 409.
- `GET /control/services/<id>`
  - 정보 보기용임. 내부 점검 대상도 담음(관리자 전용).
  - 함께 담는 것: 최근 점검 결과, 최근 장애 10건, 최근 30일 일별 가동률.
- `PATCH /control/projects/<id>`
  - 받는 값: `{name?, is_hidden?, sort_order?}`
- `POST /control/projects`
  - 받는 값: `{id, name}`
- `PATCH /control/status-page`
  - 받는 값: `{title?, notice_text?, notice_level?}`
- `GET /control/dns-candidates`
  - Cloudflare API로 zone `suhsaechan.kr`의 A/AAAA/CNAME 레코드를 읽음.
  - 실효 등록 정보의 외부 URL 호스트에 없는 이름만 돌려줌: `[{hostname, type, is_proxied}]`
  - 토큰은 env `CLOUDFLARE_API_TOKEN`, zone은 env `CLOUDFLARE_ZONE_NAME`(기본 `suhsaechan.kr`)을 씀.
  - 토큰이 없으면 503과 사유를 돌려줌.
  - 화면에서 "추가"를 누르면 `POST /control/services`(`external_url = https://{hostname}/`)를 부름.
- 변경 API는 모두 감사 로그(기존 audit 패턴)를 남김. 다음 폴러 틱(60초 안)에 반영됨.

## 계약 5: 관리자 화면
- 관제소 페이지에 탭 3개를 둠: **현황**(기존) / **서비스 관리** / **상태 페이지**
- 서비스 관리
  - 프로젝트별 표를 보여 줌. 행마다 이름 인라인 수정, 추적 상태 선택(추적함/감시만/추적 안 함), 공개 토글, 순서 위·아래, 주소, **정보** 버튼(창)을 둠.
  - "추적 안 함" 서비스는 아래쪽에 흐리게 보여 줌.
  - 서비스 추가 폼과 **Cloudflare DNS에서 가져오기** 목록을 둠.
  - 프로젝트 이름 수정, 숨김, 순서, 추가를 할 수 있음.
- 상태 페이지 탭
  - 사이트 이름, 공지 문구·수준, 미리보기 링크(https://status.suhsaechan.kr)를 둠.
- DaisyUI와 기존 토큰·컴포넌트 패턴을 따름. JS 파일은 300줄 이하로 나눔.

## 계약 6: 공개 페이지 개편 (Worker)
- 참고한 페이지: status.claude.com, status.openai.com, githubstatus.com
- 구성
  - 머리: Twin-Fang 로고 + 사이트 이름
  - 큰 전체 상태 배너: 정상은 초록, 일부 장애는 주황, 큰 장애는 빨강
  - 공지 배너(있을 때)
  - **진행 중 장애 카드**: 서비스, 시작 시각, 경과 시간
  - **프로젝트 묶음**: 접기·펼치기(`<details>`, JS 없이). 머리에 구성 요소 수, 90일 묶음 가동률, 묶음 상태 점을 둠.
  - 서비스 행: 이름, 상태, 90일 막대. 막대에 마우스를 올리면 CSS 툴팁으로 날짜와 가동률이 나옴(`data-*` + `::after`, JS 없음). 오늘 막대는 실시간 상태를 씀.
  - **최근 14일 날짜별 장애 목록**: 장애가 없는 날은 "장애 없음"
  - 바닥: 마지막 갱신 시각, "Powered by SUH 관제소"
- 라이트·다크(`prefers-color-scheme`)를 지원함. 색은 CSS 변수 토큰으로만 씀. 모바일 360px에서 가로 스크롤이 없어야 함.
- 무료 한도: fetch CPU 10ms. 기존처럼 meta만 읽고 60초 캐시함. 큰 이미지는 base64 모듈로 한 번만 디코드함.

## 계약 7: SEO (Worker)
- `<title>{title}</title>`
- 메타 태그
  - `meta description`: "SUHSAECHAN(Cassiiopeia) 서비스 실시간 상태와 90일 가동률 - elum, romrom, passql 등" (공개 프로젝트 이름으로 생성)
  - 대표 주소: `link rel=canonical` = `https://status.suhsaechan.kr/`
  - Open Graph: `og:title`, `og:description`, `og:type=website`, `og:url`, `og:image=https://status.suhsaechan.kr/og.png`, `og:site_name`
  - 트위터: `twitter:card=summary`
  - `theme-color`, `lang="ko"`
- 아이콘 경로: `/favicon.ico`, `/favicon.png`, `/apple-touch-icon.png`, `/og.png`, `/logo.png`
  - `brand/`에서 생성 스크립트로 만든 base64 모듈에서 서빙함.
  - `Cache-Control: public, max-age=86400`
- `/robots.txt`: 전체 허용 + `Sitemap: https://status.suhsaechan.kr/sitemap.xml`
- `/sitemap.xml`: 루트 1개, `lastmod`는 오늘
- JSON-LD: `WebSite`(name, alternateName `["Cassiiopeia Status","SUHSAECHAN Status"]`, url) + `Organization`(name SUHSAECHAN, logo)
- CSP는 `img-src 'self' data:`와 인라인 JSON-LD를 허용하도록 맞춤. `nosniff`는 유지함.

## 하지 않는 것
- 등록 파일 자동 수정(레포 커밋) 없음
- 외부 구독(메일·RSS) 없음
- 인증 방식 변경 없음
