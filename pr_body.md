<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * Ollama 대형 모델 연속 테스트 시 타임아웃이나 예외가 발생하더라도 VRAM 메모리가 항상 정상 해제되도록 백엔드 생명주기 관리 구조 도입

* **버그 수정**
  * 실패한 모델 개별 재시도(Retry) 시에도 VRAM 자동 언로드 정책이 올바르게 작동하도록 조치하여 메모리 누수 원천 차단

* **개선**
  * VRAM 강제 해제 엔드포인트를 공식 규격으로 전환하여 보다 완벽하고 안전한 메모리 반환 보증
  * 윈도우 및 NSSM SYSTEM 특수 권한 환경에서도 Ollama 실시간 구동 로그(server.log)를 완전히 탐색할 수 있는 로그 스캐너 기능 고도화

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

