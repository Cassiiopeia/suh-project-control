# 팰월드 관리 페이지 레이아웃 개편 — 게임 로그 우선 · 플레이어 상시 노출 (#76)

- 날짜: 2026-07-15
- 상태: 사용자 승인 (AskUserQuestion 3건으로 확정)
- 관련: 이슈 https://github.com/Cassiiopeia/suh-project-control/issues/76

## 1. 확정 요구사항

1. **페이지 순서 재배치**: 서버 상태 카드 → **탭 섹션(위로 이동)** → 월드·서버 정보 카드 → 게임 접속 방법 카드
2. **탭 구성 [로그✓][설정][백업]** — 로그가 첫 탭이자 기본 선택(checked), 플레이어 탭 제거
3. **로그 기본 소스 = 게임 로그(PalServer 원본)** — 뷰어가 `sources[0]`을 기본 선택하므로 배열 순서를
   `게임 로그 → 이벤트 → 감사 → 오류(stderr) → 시스템(Flask)`으로 변경
4. **플레이어 상시 노출**: 서버 상태 카드 안(스파크라인 아래)에 기존 7컬럼 테이블(이름·계정·레벨·Ping·SteamID·IP·좌표)
   + "관리자만 볼 수 있는 정보" 안내문을 통째로 이식. 컨테이너 `<div id="players-section" class="hidden">`,
   소제목 "접속 중인 플레이어". **접속자 있을 때만 표시, 0명이면 영역 전체 숨김**
5. **CSS 규칙**: daisyUI native 컴포넌트만, 커스텀 CSS 추가 금지, 테마 시맨틱 토큰만 사용 (다크/라이트 모두 지원 유지)

## 2. 구현

### palworld.html
- 탭 섹션(`<div role="tablist" class="tabs tabs-lift">`)을 서버 상태 카드 바로 아래로 이동
- 탭 순서: 로그(checked) → 설정 → 백업. 플레이어 탭(input+tabpanel) 삭제
- 플레이어 테이블 블록을 서버 상태 카드 card-body 맨 아래에 이식:
  ```html
  <div id="players-section" class="hidden">
    <h3 class="font-medium text-sm mb-2 flex items-center gap-2">
      <i data-lucide="users" class="size-4"></i>접속 중인 플레이어
    </h3>
    <div class="overflow-x-auto">
      <table class="table table-sm"> …기존 thead/tbody(#player-list) 그대로… </table>
    </div>
    <p class="text-xs opacity-50 mt-2">SteamID·IP·좌표는 관리자만 볼 수 있는 정보입니다.</p>
  </div>
  ```
- 월드·서버 정보 카드와 게임 접속 방법 카드는 탭 섹션 아래로 내림 (내용 변경 없음)
- **주의**: #73에서 추가된 서버 빌드 업데이트 영역(배지/버튼/진행 패널)은 서버 상태 카드 안 현 위치 유지

### palworld.js
- `initLogViewer()` sources 순서: `game, events, audit, stderr, flask`
- `renderPlayers(players)`: 기존 tbody 렌더 유지 + 마지막에
  `document.getElementById('players-section')?.classList.toggle('hidden', !(players && players.length))`

### 검증
- CSS 재빌드(`npm run build`) — 신규 클래스 없음 예상이지만 템플릿 변경이므로 재빌드 원칙 준수
- 전체 pytest 118개 회귀 없음 (백엔드 무변경)
- 렌더 스모크: `/admin/palworld` 응답에 `players-section` 존재, 로그 탭 input에 `checked`, 플레이어 탭 부재 확인

## 3. 범위 제외

- 로그 뷰어 내부 변경, 설정/백업 탭 내용 변경, 플레이어 테이블 컬럼 변경 없음
