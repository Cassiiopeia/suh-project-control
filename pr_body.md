<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * Ollama Structured Output 테스트 페이지에서 여러 모델을 계열(Family)별로 묶어 다중 선택 및 벤치마킹할 수 있는 기능 추가
  * 선택된 모델들을 순차 비동기 호출로 안전하게 실행하고, 실행 중간에 중단할 수 있는 중지(Abort) 제어 기능 추가

* **버그 수정**
  * 벤치마크 비동기 순차 호출 시 인증 토큰 및 API Key 헤더 정보가 누락되어 `Unauthorized` 권한 오류가 발생하던 결함 수정

* **개선**
  * 총 처리 시간, 모델 로딩 지연, 추론 소요 시간, 입출력 토큰 규모 및 초당 토큰 속도(tok/s)를 한눈에 대조해 볼 수 있는 벤치마크 요약 테이블 추가
  * 반환된 구조화 JSON 응답 결과가 기재된 JSON Schema 사양을 완벽히 충족하는지 가볍게 즉석 평가해 주는 자체 스키마 검증기 도입
  * 사용자가 작성 중이던 프롬프트, 온도, JSON Schema 템릿 및 모델 선택 체크 상태가 새로고침 시에도 날아가지 않도록 로컬 세션 영구 보존 정책 적용

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

