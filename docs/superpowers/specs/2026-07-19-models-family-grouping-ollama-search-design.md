# 모델 관리 페이지 개선 설계 — 패밀리 그룹핑 + Ollama 라이브러리 검색

- 이슈: https://github.com/Cassiiopeia/suh-project-control/issues/105
- 대상: `suh-ai-server/flask` — `/admin/models` 페이지
- 날짜: 2026-07-19

## 배경 / 문제

1. 테스트·벤치마크 모델 선택 리스트가 이름순 평면 나열이라 `hf.co/...` 긴 레포명과 일반
   모델명이 뒤섞여 원하는 모델을 찾기 어렵다.
2. 모델 검색이 Hugging Face GGUF 검색만 지원되어, Ollama 공식 라이브러리 모델은
   pull 명령어를 미리 알아야만 설치할 수 있다.

## 결정 사항 (사용자 확인 완료)

| 항목 | 결정 |
|---|---|
| 그룹핑 기준 | 모델명 prefix(`:` 앞부분). `hf.co/...`는 `HuggingFace` 그룹으로 분리해 맨 아래 배치 |
| 적용 범위 | 벤치마크 선택 리스트(그룹 헤더) + 설치된 모델 테이블(패밀리→이름순 정렬) |
| Ollama 검색 | `ollama.com` HTML 파싱 (공식 API 없음). 검색→태그 목록→기존 다운로드 큐로 받기 |
| 검색 UI | 검색 1회에 Ollama·HF 병렬 호출, 두 결과 섹션 나란히 표시 |

## 아키텍처

### 1. 백엔드 — `service/model_service.py`

- `search_ollama_models(query, limit=20)`
  - `GET https://ollama.com/search?q={query}` (User-Agent 지정, timeout 15s)
  - `<li>` 블록 단위 정규식 파싱:
    - 모델명: `<a href="/library/{name}">`
    - 설명: `<p class="max-w-lg break-words ...">`
    - capability 태그(indigo 스팬): vision/tools/thinking/embedding 등
    - 사이즈 태그(blue 스팬): 1b, 4b, e2b ...
    - pull 수: `<span>18.7M</span><span ...>&nbsp;Pulls</span>`
  - 반환: `[{'name','description','pulls','capabilities','sizes'}]`
- `list_ollama_tags(name)`
  - `GET https://ollama.com/library/{name}/tags`
  - 태그별 파싱(모바일/데스크톱 중복 → dedup): 태그명, digest, 크기(`3.3GB`), context window
  - 반환: `[{'tag','full_name'('gemma3:4b'),'size_text','context','digest'}]`
- 파싱 결과 0건 + HTTP 200이면 "사이트 구조 변경 가능성" 로그. HTTP 오류는 예외 전파.

### 2. 백엔드 — `router/model_router.py`

- `GET /models/ollama/search?q=` → `search_ollama_models`
- `GET /models/ollama/tags?name=` → `list_ollama_tags`
- 오류 시 `{'error': ...}` 500 — 기존 라우터 패턴과 동일

### 3. 프론트 — `static/js/models.js`

- `familyOf(name)`: `hf.co/` 시작 → `'HuggingFace'`, 아니면 `name.split(':')[0]`
- `groupByFamily(models)`: 패밀리별 묶음, 패밀리 알파벳순 + `HuggingFace` 마지막
- `renderBenchModels()`: 그룹 헤더(패밀리명+개수, divider) 아래 체크박스 나열 (기존 vision
  비활성화·선택 유지 로직 그대로)
- `renderInstalled()`: 패밀리→이름순 정렬 후 렌더 (컬럼 구조 유지)
- 검색: `searchAll()`이 `/models/ollama/search`와 `/models/search`(HF)를 `Promise.allSettled`로
  병렬 호출. 각 섹션 독립 로딩/에러 표시 (한쪽 실패해도 다른 쪽 표시)
- Ollama 결과 클릭 → `/models/ollama/tags` → 태그 테이블([받기] = 기존 `enqueuePull(full_name)`)

### 4. 프론트 — `templates/admin/models.html`

- 검색 카드 제목을 "모델 검색 (Ollama · Hugging Face)"로 변경
- 결과 영역을 2열 그리드(모바일 1열): "Ollama 라이브러리" 섹션 + "Hugging Face" 섹션
- Ollama 태그 목록 테이블 추가 (HF GGUF 파일 테이블과 동일 패턴)

## 오류 처리

- Ollama/HF 각각 독립 실패 처리 — 실패 섹션에만 에러 행 표시
- 파싱 실패(구조 변경): "Ollama 사이트 구조가 변경되어 검색에 실패했습니다" 안내
- gated HF 모델 403 처리는 기존 로직 유지

## 테스트

- `test/test_model_service.py`: 저장한 HTML 샘플 축약본으로 `search_ollama_models`·
  `list_ollama_tags` 파싱 검증 (requests mock)
- `test/test_model_router.py`: 신규 엔드포인트 성공/파라미터 누락/서비스 예외 케이스

## 비범위 (YAGNI)

- Ollama 검색 결과 페이지네이션, 정렬 옵션
- HF 검색 로직 변경
- 다운로드 큐 로직 변경 (그대로 재사용)
