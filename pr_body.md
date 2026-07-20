<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

* **새 기능**
  * **Ollama 관리 어드민 대시보드 전격 개설 (`/admin/ollama`)**:
    * **데몬 프로세스 제어**: 현재 구동 여부 생사 지시등, 시작/중지/재시작 물리 조작 패널 장착
    * **VRAM 실시간 점유 감지**: 현재 GPU 메모리에 실시간 로드되어 VRAM을 잠식 중인 활성 모델명 및 크기 실시간 모니터링, 수동 메모리 강제 반환(Unload) 기어 구축
    * **실시간 로그 스트리밍**: 윈도우즈 서버 깊숙이 은닉된 `server.log`를 자동 추적하여 에러 식별 컬러가 가미된 최근 200줄의 로깅 실시간 스트리밍 뷰 탑재
  * **윈도우 권한 제약 극복 2중 제어 및 로그 자동 스캐너**:
    * 파워쉘 서비스 리부트 명령 실패 시, 강제 프로세스 종료(`taskkill`) 및 콘솔 팝업을 은닉하는 무창 백그라운드 서빙 데몬 기동(`subprocess.Popen(["ollama", "serve"])`)으로의 우아한 2중 폴백 수립
    * 윈도우 OS의 특성을 고려해 홈 디렉토리 명세를 동적 추적해 `~/.ollama/` 및 `AppData` 하위 logs 경로를 자동 발굴하는 자율 스캐너 구축
  * **벤치마킹 연속 구동 VRAM 청소 기어 탑재**:
    * Ollama 테스트 요청 구성에 "자동 VRAM 청소 정책 (Auto Unload)" 토글 스위치(기본값: ON)를 추가 배치
    * 실행 기동 시, 개별 모델의 추론 및 원격 DB 적재가 끝난 직후 백엔드로 Unload 시그널을 즉시 쏘아 보내어, VRAM 누적 잠식 한도를 상시 최저치로 순화 (OOM 및 Gateway Timeout 원천 차단 완결)

<!-- end of auto-generated comment: release notes by coderabbit.ai -->

