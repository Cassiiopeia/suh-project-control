# Admin 대시보드 카드 보완 + API 문서 iframe 임베드 설계

날짜: 2026-07-19
대상: `suh-ai-server/flask` 관리자 페이지

## 문제

1. 사이드바 메뉴 7개(대시보드·팰월드·Ollama 테스트·모델 관리·TTS 관리·API 문서·Flask 로그) 중
   대시보드 바로가기 카드에 **TTS 관리가 누락**되어 있다.
2. **API 문서**가 `/docs/swagger`(flask-swagger-ui 기본 페이지)로 이동해 admin 레이아웃을
   이탈한다. 사이드바·테마·네비바가 사라지고 별도 사이트처럼 보인다.

## 설계

### 1. 대시보드 TTS 카드 추가
- `templates/admin/dashboard.html` 카드 그리드에 TTS 관리 카드 추가 (`./admin/tts`, `audio-lines` 아이콘).
- 사이드바 순서(팰월드 → Ollama → 모델 → TTS → API 문서 → 로그)와 동일하게 배치.

### 2. API 문서 iframe 임베드 페이지
- `router/admin_router.py`에 `GET /admin/api-docs` 라우트 추가
  (`render_template('admin/api_docs.html', root='..', active='api-docs')`).
- `templates/admin/api_docs.html` 신규: `admin/base.html` 확장, content 블록에
  전체 폭 iframe으로 `{{ root }}/docs/swagger` 임베드. 높이는 뷰포트 기준
  `calc(100vh - 헤더/패딩/푸터)`로 채우고, 스크롤은 iframe 내부(스웨거 UI)에서 처리.
- `templates/admin/base.html` 사이드바의 API 문서 링크를 `{{ root }}/admin/api-docs`로
  교체하고 `active == 'api-docs'` 시 `menu-active` 클래스 적용.
- `templates/admin/dashboard.html`의 API 문서 카드 링크도 `./admin/api-docs`로 교체.
- 기존 `/docs/swagger` 라우트는 iframe 소스로 그대로 사용 (직접 접근도 계속 가능).

## 검증
- Flask 앱 기동 후 `/admin`, `/admin/api-docs` 응답 및 iframe 소스 경로 확인.
- 기존 테스트 스위트(`flask/test`) 실행.
