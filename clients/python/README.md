# suh-control-tower (Python)

> **서버 전용 클라이언트입니다. 모바일 앱(Android/iOS)에 넣지 마세요.** 프로젝트 토큰이 앱에 들어가면 누구나 꺼낼 수 있습니다.
> 어떤 내용을 보낼지(개인정보 포함 여부)는 보내는 쪽이 판단합니다. 이메일, 전화번호 같은 개인정보는 `title`, `body`, `fields`에 넣지 마세요.

관제소 알림 허브(`POST /control/events`)로 "지금 일어난 일"을 보내는 의존성 없는 Python 클라이언트입니다(Python 3.9 이상). 규격은 [events 가이드](../../docs/control-tower/events/README.md)가 원본입니다.

## 설치

아직 PyPI에 게시하지 않았습니다. 소스에서 설치하세요.

```bash
pip install ./clients/python
```

## 사용

토큰은 관제소 관리 화면(서비스 관리 > 프로젝트 > 이벤트 토큰)에서 발급해 환경변수에 둡니다.

```python
import os
import suh_control_tower

suh_control_tower.init(   # 키워드 전용, project와 token 필수
    project="my-project",
    token=os.environ["CONTROL_TOWER_TOKEN"],  # 교체 시 환경변수만 바꾸고 재시작
    # base_url 기본값: https://ai.suhsaechan.kr/api/flask, timeout_seconds 기본값: 3
)

result = suh_control_tower.notify(
    kind="error", title="결제 실패", severity="critical",
    body="결제 승인 응답 지연", url="https://example.com/orders/42",
    fields={"주문": "42", "원인": "timeout"},   # dict 또는 [(이름, 값), ...] (순서 유지)
    dedupe_key="payment-error:42",
)
```

`init`을 쓰지 않고 `ControlTowerClient(project=..., token=...)`를 직접 만들어 써도 됩니다(스레드 안전, 인자는 모두 키워드 전용).

- 설정 오류는 `init`/생성자에서 `ValueError`로 알립니다: 빈 `project`/`token`, 공백·제어문자·비ASCII가 든 토큰, `https`가 아닌 `base_url`(테스트용 `http://127.0.0.1`, `http://localhost`만 예외). 앱 시작 시 한 번 걸러집니다.
- `notify`/`notify_in_background`는 예외를 던지지 않습니다.
- `timeout_seconds`는 소켓 동작(연결, 읽기)마다 적용되며 전체 소요 시간 상한이 아닙니다.
- 리다이렉트(3xx)는 따라가지 않습니다(토큰 유출 방지). 결과는 `http_302`처럼 실제 상태로 나옵니다.

### Flask / FastAPI 요청 처리 안에서

알림 때문에 응답이 늦어지지 않도록 `notify_in_background`를 씁니다. 데몬 스레드라서 프로세스가 종료되면 진행 중이던 전송은 버려지고, 결과는 받을 수 없습니다(`init` 전에 호출하면 `None`을 돌려줍니다).

```python
@app.post("/reports")           # Flask, FastAPI 모두 동일
def create_report():
    ...
    suh_control_tower.notify_in_background(
        kind="report", title="신고 접수", fields={"신고 번호": str(report_id)},
        dedupe_key="report:%s" % report_id)
    return {"ok": True}
```

앱 시작 시(Flask 앱 생성 직후, FastAPI `lifespan`) `init`을 한 번 호출합니다.

## 결과 처리

`notify`는 예외를 던지지 않고 `NotifyResult`를 돌려줍니다.

| 필드 | 뜻 |
|---|---|
| `is_accepted` | 서버가 접수(202)했는지 |
| `status_code` | HTTP 상태 (네트워크 오류, 시간 초과, init 전은 `None`) |
| `error_code` | 서버 `error` 값(`invalid`, `unknown_kind`, `unauthorized`, `unknown_project`, `unavailable`), JSON이 아닌 응답은 `http_<상태>`(예 `http_413`), `timeout`, `connection_error`, `not_initialized`, `invalid_input`(보내기 전 로컬 검증 실패, 예 필드 값이 `None`. 서버의 `invalid`와 구분) |
| `is_deduplicated` | `dedupe_key` 중복으로 알림 없이 접수만 됨 |

```python
if not result.is_accepted:
    logger.warning("[control-tower client] not delivered : %s", result.error_code)
```

`unavailable`, `timeout`, `connection_error`는 잠시 뒤 같은 `dedupe_key`로 재시도할 수 있습니다. 토큰은 로그, `repr`, 예외 메시지에 넣지 않습니다.
