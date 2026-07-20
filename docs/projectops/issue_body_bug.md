## 버그 현상 요약
Ollama Structured Output 연속 벤치마크 테스트 도중, 대형 모델(7.8B, 8B 등)을 연속으로 거치는 구간에서 다수의 모델들이 대거 `실패` 상태로 전이되며 **`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`** 파싱 오류가 발생하는 결함이 발견되었습니다.

## 원인 분석 (VRAM 포화 및 Timeout)
- **Ollama의 메모리 홀딩 정책**: Ollama는 한번 GPU 메모리에 올린 모델을 `keep_alive` 정책(기본 5분)에 의해 VRAM에서 내리지 않고 상주시킵니다.
- **물리 VRAM 초과(OOM) 및 스왑 병목**: 연속으로 수많은 대형 모델들을 차례대로 올리면 로컬 GPU VRAM 한계를 급격히 초과하여 Out-of-Memory 상태가 됩니다. 윈도우 OS가 느린 시스템 램으로 메모리 페이징 스왑을 유발하는 과정에서 **수십 초 간 극심한 연산 병목(System Hang/Freeze)** 상태가 일어납니다.
- **HTTP Timeout 및 HTML 반환**: 이 지연 시간이 Nginx 및 Flask Waitress 서빙 대기 제한 시간인 60초를 가볍게 넘겨버려 원격 게이트웨이 타임아웃(504/502 Bad Gateway)이 유발됩니다. 이로 인해 Flask가 JSON 대신 Nginx 에러 HTML 페이지를 반환하게 되며 프론트엔드 단의 파싱 파괴를 유발합니다.

## 조치 설계 방안
- 실시간으로 구동되는 Ollama 로그를 추적하여 타임아웃 시점을 모니터링할 수 있는 구체적인 가시화 뷰를 마련해야 합니다.
- 벤치마크 기동 전 혹은 개별 모델 추론 직후, VRAM에 누적된 모델들을 백엔드에서 주도적으로 안전 강제 해제(`keep_alive: 0`) 시켜 VRAM 점유 한도를 상시 최저치로 순화시키는 조치 장치를 연동해야 합니다.
