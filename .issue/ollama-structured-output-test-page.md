⚙️ [기능추가][suh-ai-server] Ollama Structured Output(JSON Schema) 테스트 페이지 추가
===

📝 배경 / 현재 문제점
---

- Ollama는 `format` 파라미터에 JSON Schema를 전달하면 디코딩 단계에서 출력 구조를 강제하는 **Structured Outputs**를 지원함 (#31 고찰 참고)
- 하지만 4B급 소형 모델(gemma3:4b 등)에서 중첩 Object·배열·enum 스키마가 실제로 얼마나 잘 강제되는지, 모델별 응답 속도는 어떤지 확인할 수단이 없음
- 매번 curl로 스키마를 만들어 수동 테스트하는 것은 번거로움

🛠️ 해결 방안 / 제안 기능
---

- [x] 관리자 페이지에 **Ollama 테스트** 페이지 추가 (`/admin/ollama-test`)
- [x] Flask 테스트 엔드포인트 2종 추가 (OCR/Vision과 동일하게 내부 `ollama.Client` 재사용)
  - `GET /ollama/models` — 설치된 모델 목록 (이름·용량·파라미터 크기)
  - `POST /ollama/chat` — model/prompt/system/temperature/format 전달, stream=false
- [x] format 3모드 토글: 없음 / `"json"` / JSON Schema — 모드별 차이 비교
- [x] JSON Schema 프리셋 4종: 단순 객체 / 중첩 객체 / 배열 속 Object / enum 포함
- [x] 스키마 실시간 JSON 유효성 검사 (오류 시 실행 비활성)
- [x] 결과 카드 누적: 모델명·format 모드·소요시간·tok/s 배지, 응답 `JSON.parse` 성공 여부 배지("유효 JSON"/"파싱 실패") — 모델 바꿔가며 실행하면 자연스럽게 비교
- [x] 사이드바 메뉴·대시보드 카드 추가

⚙️ 작업 내용
---

- `service/ollama_service.py` (신규) — 모델 목록·structured chat, ns→ms 메트릭 계산
- `router/ollama_router.py` (신규) — 파라미터 검증(400)·Ollama 장애 JSON 에러(500)
- `templates/admin/ollama-test.html` + `static/js/ollama-test.js` (신규)
- `admin_router.py`·`base.html`·`dashboard.html` — 라우트·메뉴·카드
- daisyUI 5 `fieldset`/`fieldset-legend` 네이티브 패턴 적용, Tailwind 재빌드
- `test/test_ollama_router.py` — 단위 테스트 11종 (전체 152 passed)

🔗 관련 이슈
---

- #31 Json Format Ollama API 지원에 대한 고찰
- #41 Ollama 버전 업데이트 및 gemma4 모델 다운로드 (structured outputs는 현 버전에서도 동작)

🙋‍♂️ 담당자
---

- 백엔드/프론트: Cassiiopeia
