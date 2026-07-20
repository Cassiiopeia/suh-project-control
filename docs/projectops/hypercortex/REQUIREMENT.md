# REQUIREMENT

## [PROBLEM]
다중 모델 구조화 출력 벤치마크 수행 중, Ollama 서버가 대형 모델(7.8B 등)을 연속 로드하는 과정에서 시스템 VRAM(GPU 메모리) 한도를 초과해 일시적 혹은 영구적으로 서비스가 응답 불능(Hang) 상태가 됩니다.
이로 인해 다음과 같은 심각한 사용자 피로가 유발됩니다.
1. **Timeout 및 HTML 반환 실패**: Nginx 프록시 및 Flask Waitress 서빙 대기 시간(보통 60초)을 초과하여 504 Gateway Timeout 혹은 500 에러를 뱉게 되며, 프론트 단에서는 JSON 파싱 실패 에러(`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`)가 빈발하며 대다수 모델이 줄줄이 실패하게 됩니다.
2. **메모리 고립 현상**: Ollama의 기본 메모리 유지 정책(`keep_alive` 기본 5분) 때문에 이전 대형 모델이 GPU에 갇혀 있어, 다음 모델이 설령 가볍더라도 로딩 지연이 수십 초씩 연속적으로 발생합니다.
3. **블라인드 디버깅 한계**: Ollama의 실행 과정과 VRAM 점유 정보, GPU 에러 발생 여부가 담긴 Ollama `server.log` 정보가 로컬 서버 윈도우 깊은 곳에 은닉되어 있어 내부망 외부의 웹브라우저 상에서는 원인 진단이 전혀 불가능합니다.

## [REQUIREMENT]

### 1. Flask Admin 내 독립적인 'Ollama 제어' 탭 개설 (UI/UX)
- 왼쪽 네비게이션 탭에 **"Ollama 관리"** 메뉴를 추가하여 팰월드 서버 제어와 유사한 독자 관리 대시보드를 전격 구축합니다.
- 대시보드는 세 영역으로 구성됩니다:
  - **Ollama 서비스 제어**: 구동 프로세스 상태 실시간 체크, 서비스 강제 재기동(Restart), 강제 중지(Stop)
  - **VRAM 점유 및 활성 모델 제어**: 현재 VRAM에 로드되어 살아 있는 활성 모델 목록 실시간 모니터링, **"VRAM 강제 청소 (Unload)"** 원버튼 지원
  - **Ollama 실시간 로그 뷰어**: 로컬 윈도우 서버 내의 `server.log` 경로를 자동 추적하여 최근 200줄의 구동 로그 및 에러 메시지 실시간 스트리밍 시각화

### 2. 백엔드 시스템 제어 및 자동 탐색 아키텍처 (Flask / PowerShell)
- **Ollama 윈도우 서비스 제어**: PowerShell 및 `NSSM` 혹은 윈도우 서비스 관리 명령어(`Restart-Service -Name Ollama`, `Stop-Process -Name ollama`)를 백엔드에서 안전하게 기동하여 프로세스를 강제 소생시킵니다.
- **VRAM 모델 모니터링 및 Unload API 연계**:
  - `GET http://127.0.0.1:11434/api/ps` API를 호출해 현재 메모리에 실시간 로드되어 있는 활성 모델 리스트를 수집합니다.
  - 특정 모델 또는 전체 활성 모델에 대해 `keep_alive: 0` 을 탑재한 대화 신호를 전송하여 VRAM에서 즉시 소멸(Unload)시킵니다.
- **Ollama `server.log` 고정 경로 전수 탐색**:
  - 윈도우즈 OS 환경에서 구동 중인 Ollama 로그의 세 가지 기본 설치 후보 경로를 백엔드 기동 시 차례대로 자동 스캔하여 실제 존재하는 로그 파일 경로를 자동 바인딩합니다:
    1. `C:\Users\<사용자명>\.ollama\logs\server.log`
    2. `C:\Users\<사용자명>\AppData\Local\Ollama\server.log`
    3. `C:\Windows\System32\config\systemprofile\.ollama\logs\server.log`

### 3. 벤치마크 연계 최적화 (OOM 원천 차단 정책)
- Ollama 테스트 구성 옵션에 **"테스트 전 VRAM 자동 Unload"** 및 **"개별 모델 실행 후 강제 메모리 해제"** 토글 옵션을 추가합니다.
- 이 옵션 활성 시, 벤치마크 기동 전 혹은 매 모델 추론이 완료되어 결과가 DB에 저장된 직후 백엔드에서 해당 모델을 즉각 메모리에서 소멸(`keep_alive: 0`)시켜 VRAM 점유율을 항상 `0%`에 가깝게 유지해 대형 모델 연속 구동 OOM을 원천 무효화합니다.

---

## [REVIEW_LOG]
* **검토자**: Reviewer Persona
* **검토 의견**:
  - **Critical Edge Case 1 (권한 제약 및 보안 가드)**: 윈도우에서 `ollama.exe` 프로세스를 강제 종료하거나 서비스를 재기동할 때, Flask 웹 서버를 실행 중인 윈도우 계정(USER 등)의 권한 수준에 따라 서비스 기동 및 중지 명령어(`Restart-Service` 등)가 권한 거부(Access Denied) 에러로 실패할 수 있습니다. 이를 방어하기 위해, 서비스 관리 명령이 실패하면 일반 사용자 권한으로도 기동 가능한 **태스크킬 프로세스 중지 방식(`taskkill /F /IM ollama.exe`) 및 Ollama 데몬 백그라운드 재실행 방식**으로 정교하게 폴백하는 윈도우 명령 래퍼를 구성해야 완벽하게 안전합니다.
  - **보안 감사**: Ollama 프로세스를 죽이고 다시 켜거나, VRAM을 청소하는 행위는 전체 시스템의 추론 무결성에 영항을 주므로 무조건 `AuditCategory.SYSTEM` 카테고리 하위에 속하는 정형 감사 로그(`@audited`)를 탑재하여 연동해야 합니다.
