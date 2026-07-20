<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **버그 수정**
  * **공식 벤치마크 Unload API 전격 개편**: 기존 `/api/chat` 에 비어있는 메시지를 보내 메모리를 해제하려던 방식이 일부 윈도우용 구버전 빌드에서 파라미터 에러로 오작동을 무시하던 결함을 발견하고, 공식 반환 표준인 `/api/generate` 엔드포인트에 `prompt: ""` 와 `keep_alive: 0` 을 전송하는 방식으로 백엔드를 전수 개편하여 윈도우 실서비스에서도 VRAM이 100% 무결하게 즉시 청소(Unload)됨을 완전 보증
  * **NSSM 서비스 계정 로그 수집 결함 우회**: 윈도우즈 가상 서비스 계정 권한(`SYSTEM`)으로 구동되어 실제 개발자 유저 디렉토리(`C:\Users\chan4`)를 동적 탐색하지 못해 logs 조회가 `없음`으로 표출되던 문제를 타파하기 위해, 백엔드 기동 즉시 `C:\Users\` 디렉토리 하위 전수를 자율적으로 와일드카드 스캔하여 실시간 `server.log` 물리 절대경로를 귀신같이 추적해내는 전수 디렉토리 스캐너 탑재

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

