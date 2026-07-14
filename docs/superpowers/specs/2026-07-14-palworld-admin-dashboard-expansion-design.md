# 팰월드 관리자 대시보드 대폭 확충 — 설계 (Issue #57 게임로그 정상화 후속)

작성일: 2026-07-14
관련: 게임로그 정상화(#56/PR#57), 대시보드 확충(신규 이슈), 로그 뷰어 강화(신규 이슈)

## 목표

관리자 화면에서 팰월드 서버의 **가능한 모든 정보를 추적·조회**할 수 있게 한다.
현재는 접속자 수 / FPS / 업타임 / (이름·레벨·Ping) 3열 플레이어 표만 노출된다.
PalServer 공식 REST API(`/info` `/players` `/metrics` `/settings`)는 훨씬 많은 데이터를 제공하므로 이를 전면 노출하고, 시간에 따른 추이를 그래프로 본다. 기존의 깔끔한 DaisyUI 레이아웃 톤은 유지한다.

## 범위 (두 이슈로 분리)

### 이슈 A — 대시보드 정보 확충 + 메트릭 히스토리
1. **서버 성능 지표 확충**: 평균 FPS, 프레임타임(ms), 인게임 일수(days), 거점 수(basecampnum), 최대 인원. `/metrics` 전량.
2. **플레이어 상세**: 이름·레벨·Ping에 더해 계정명(Steam 닉)·SteamID(userId)·IP·월드 좌표(X/Y). `/players` 전량. 민감정보(IP·SteamID)는 노출하되 표에 정리.
3. **월드/서버 정보**: 게임 버전, 월드 GUID, 서버명/설명, 자동저장 주기, 크로스플레이 플랫폼, 난이도, PvP 여부 등 `/info`+`/settings` 요약 카드.
4. **메트릭 시계열 히스토리 + 그래프**: 서버가 순간값만 주므로 Flask가 주기적으로 metrics 스냅샷을 링버퍼(+jsonl 영속)에 적재. `/palworld/history` 엔드포인트로 최근 N개 반환. 프론트는 인라인 SVG 스파크라인으로 FPS·접속자 추이를 그림(외부 차트 라이브러리 없이).
5. **이벤트 폴러 강화**: `userId`(정확한 camelCase 키)로 플레이어 식별, 이벤트에 레벨·steamId 포함.

### 이슈 B — 로그 뷰어 검색/필터 + 시스템 로그
1. 로그 뷰어에 **검색어 필터**(입력창) + 레벨 필터(전체/에러/경고) + 매칭 하이라이트.
2. **시스템 로그 소스 추가**: Flask 앱 자체 로그(nssm-stderr.log 등)를 관리자에서 조회. 별도 로그 페이지/소스로.
3. 접속 이력 타임라인(events 기반)을 읽기 좋은 카드/타임라인로.

## 아키텍처

### 백엔드
- `PalworldMetricsHistory` (신규 service): 스레드 안전 링버퍼(deque, maxlen=N) + jsonl 영속(재기동 복구). 이벤트 폴러 틱마다 metrics 스냅샷 push.
  - 저장 필드: ts, currentplayernum, serverfps, serverfpsaverage, serverframetime, days, basecampnum, uptime.
  - `history(limit)` → 최근 limit개 리스트.
  - 파일: `C:\AI\palworld\logs\palworld-metrics.jsonl`, 크기 상한 회전.
- `PalworldService.get_status()`: 기존 info/players/metrics에 **settings 요약**과 **history 링크용 메타** 추가. players는 전체 필드 유지(프론트가 선택 렌더).
- 신규 라우트: `GET /palworld/history?limit=120` → `{points:[...]}`.
- 이벤트 폴러: metrics 히스토리 적재를 겸함(폴 간격 10초 → 히스토리 해상도 10초). player key를 `userId`로 정정.

### 프론트
- `palworld.html`: 상태 카드에 지표 6종, 새 "월드/서버 정보" 카드, 플레이어 탭 컬럼 확장, 상태 카드 하단 스파크라인 2개(FPS/접속자).
- `palworld.js`: `refreshStatus`가 확장 필드 렌더 + `loadHistory()`로 스파크라인 갱신. 인라인 SVG 스파크라인 헬퍼.
- `log-viewer.js`: 검색 입력 + 레벨 필터 + 하이라이트 추가(공용이므로 Flask 로그 페이지에도 자동 반영).

## 데이터 흐름
폴러 틱(10s) → REST /metrics 조회 → 히스토리 push(+jsonl append) → 프론트 5s refreshStatus + history fetch → SVG 스파크라인.

## 안전/성능
- 히스토리 파일 회전(상한 초과 시 .1 백업). 링버퍼 maxlen로 메모리 고정.
- REST 실패 시 히스토리 push 스킵(구멍 허용), 상태 카드는 degrade.
- 민감정보(IP/SteamID)는 관리자 인증 뒤에서만 노출(기존 admin nginx 인증 유지).

## 테스트
- 히스토리 링버퍼 push/limit/회전 단위 테스트.
- 폴러 metrics 적재 테스트.
- get_status settings 요약 포함 테스트.
- 로그 뷰어 검색 필터는 프론트 로직(수동/경량).

## 비범위 (YAGNI)
- 장기 시계열 DB(수개월). jsonl 링버퍼로 충분.
- 실시간 WebSocket 푸시. 폴링으로 충분.
- 플레이어 위치 지도 오버레이(좌표 숫자 노출까지만).
