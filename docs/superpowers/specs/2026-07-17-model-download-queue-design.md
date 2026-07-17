# 모델 다운로드 큐 설계

- 날짜: 2026-07-17
- 대상: suh-ai-server/flask 모델 관리 페이지 (`/admin/models`)
- 목적: 모델 다운로드를 여러 개 큐에 넣으면 서버가 순차적으로 알아서 받도록 개선

## 배경 / 문제

현재 모델 다운로드(`POST /models/pull`)는 브라우저 연결 기반 스트리밍이다.

- 프론트(`models.js`)가 `pullController`로 동시 1건만 허용 — 두 번째 '받기'를 누르면 거부됨
- 브라우저 탭을 닫거나 새로고침하면 HTTP 스트림이 끊겨 다운로드도 중단됨
- 여러 모델을 받으려면 하나 끝날 때까지 기다렸다가 수동으로 다음 것을 눌러야 함

## 합의된 요구사항

1. **서버 큐**: 큐와 다운로드 실행 주체를 Flask 서버로 이동. 탭을 닫아도 계속 진행되고, 다시 열면 상태가 보인다
2. **메모리 큐**: 서버 재시작 시 큐는 소멸. Ollama가 받다 만 레이어를 캐시하므로 다시 큐에 넣으면 이어받는다
3. **기본형 UI**: 큐 목록(대기·진행 중·완료·실패·취소) + 진행률 바 + 대기 항목 제거 + 진행 중 취소. 순서 변경은 없음
4. **워커 + 폴링 방식**: 백그라운드 워커 스레드 1개가 순차 실행, 프론트는 1.5초 간격 폴링 (SSE는 과잉으로 판단해 제외)
5. **배포 전제**: 프로덕션은 Waitress 단일 프로세스(threads=4, NSSM 단일 서비스)라 모듈 전역 큐 싱글턴이 성립한다. gunicorn 다중 워커나 다중 인스턴스로 전환하면 큐가 프로세스별로 분리되어 이 설계가 깨지므로, 전환 시 큐를 외부 저장소로 옮겨야 한다

## 아키텍처

### 신규: `service/download_queue_service.py`

`DownloadQueueService` — 메모리 큐 + 워커 스레드 1개.

큐 항목 구조:

```python
{
  'id': str,          # uuid4 hex
  'name': str,        # ollama pull 대상 (예: hf.co/unsloth/gemma-3-4b-it-GGUF:Q4_K_M)
  'status': str,      # queued | pulling | done | error | canceled
  'total': int|None,      # 전체 바이트 (pulling 중 갱신)
  'completed': int|None,  # 받은 바이트
  'error': str|None,      # 실패 사유
  'added_at': str,        # ISO8601
  'finished_at': str|None,
}
```

동작 규칙:

- `enqueue(name)`: 같은 이름이 `queued`/`pulling` 상태로 이미 있으면 `ValueError`(중복). 워커 스레드는 데몬으로 지연 기동
- 워커 루프: 큐에서 `queued` 항목을 순서대로 꺼내 `client.pull(name, stream=True)` 실행, 진행률 청크마다 `total`/`completed` 갱신
- 취소: 항목별 취소 플래그. 진행 중 항목은 워커가 청크 사이마다 플래그를 확인하고 루프 탈출(스트림 close → 다운로드 중단, 부분 레이어는 Ollama가 캐시). 대기 항목은 목록에서 즉시 제거
- 완료/실패/취소 항목은 결과 표시용으로 목록에 유지하되 최근 20개까지만 (초과분 오래된 것부터 자동 정리)
- 모든 상태 변경은 `threading.Lock`으로 보호

### API 변경 (`router/model_router.py`)

| 메서드 | 경로 | 동작 |
|---|---|---|
| POST | `/models/queue` | body `{name}` — 큐 추가. 성공 200 + 큐 상태, 중복 409 |
| GET | `/models/queue` | 큐 전체 상태 반환 (폴링용) |
| DELETE | `/models/queue/<item_id>` | 대기 항목 제거 / 진행 중 항목 취소. 없는 id는 404 |

**기존 `POST /models/pull`(NDJSON 스트리밍)은 제거.** 큐와 공존하면 동시 다운로드 경로가 생겨 큐의 의미가 없어진다. `ModelService.pull_model_stream`도 함께 제거하고 관련 테스트를 정리한다.

### 프론트엔드 (`static/js/models.js`, `templates/admin/models.html`)

- '받기' 버튼 → `POST /models/queue`, 성공 시 "큐에 추가했습니다" 토스트. 연달아 여러 개 추가 가능
- 기존 단일 진행률 박스(`pull-wrap`)를 **큐 패널**로 교체:
  - 항목별 상태 배지 (대기/다운로드 중/완료/실패/취소)
  - 진행 중 항목: 진행률 바 + `받은바이트 / 전체 (percent%)` 표시
  - 대기 항목: 제거 버튼, 진행 중 항목: 취소 버튼
- 폴링: 대기/진행 항목이 있는 동안 1.5초 간격 `GET /models/queue`, 모두 끝나면 중단. 페이지 로드 시 1회 조회해 진행 중이면 폴링 재개 (새로고침 후 상태 복원)
- 항목이 `done`으로 바뀐 것을 감지하면 설치 목록 새로고침 + 완료 토스트, `error`면 실패 토스트

## 에러 처리

- pull 실패(gated 레포, 잘못된 이름, 레포 구조 미지원 등) → 해당 항목만 `error` + 메시지 기록, 워커는 다음 항목 계속
- Ollama 서버 접속 불가 → 해당 항목 `error`, 큐 유지 (다음 항목도 시도)
- 중복 추가 → 409, 프론트는 경고 토스트
- 서버 재시작 → 큐 소멸(합의 사항). 재추가 시 Ollama 캐시로 이어받기

## 테스트

- 신규 `test/test_download_queue_service.py` (ollama Client 모킹):
  - 큐 추가 → 순차 실행 → done 전이
  - 중복 이름 추가 거부
  - 진행 중 취소 → canceled 전이, 다음 항목 진행
  - 대기 항목 제거
  - pull 예외 → error 전이 후 다음 항목 계속
  - 완료 항목 최근 20개 유지 정리
- `test/test_model_router.py`: 큐 API 3개 엔드포인트 테스트 추가, `/models/pull` 테스트 제거

## 제외 범위 (YAGNI)

- 큐 영속화(DB/파일), 순서 변경, 동시 다운로드 수 설정, SSE 푸시, 다운로드 속도 표시
