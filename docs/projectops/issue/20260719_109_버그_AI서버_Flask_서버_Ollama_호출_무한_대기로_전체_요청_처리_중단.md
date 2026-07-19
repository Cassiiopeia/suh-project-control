🗒️ 설명
---

- AI 서버(Windows)의 Flask 서버가 살아있는 것처럼 보이지만(서비스 Running, 포트 5000 리슨) 모든 HTTP 요청에 응답하지 못하는 행(hang) 상태에 빠진다.
- 원인: Ollama API 호출(`ollama.Client`)에 타임아웃이 설정돼 있지 않아, Ollama가 응답을 주지 않으면 해당 요청을 처리하던 waitress 워커 스레드가 무한 대기한다.
- waitress 워커 스레드가 4개뿐이라, Ollama에 막힌 요청이 4개 쌓이면 서버 전체가 어떤 요청도 처리하지 못한다 (팰월드 관리 페이지 등 Ollama와 무관한 기능까지 전부 마비).
- 2026-07-19 17:01경 실제 발생: `gemma3:4b-it-qat` chat 호출 이후 워커가 전부 소진되어 요청 큐가 38개까지 누적, 서비스 재시작으로 임시 복구함.

🔄 재현 방법
---

1. Ollama가 응답이 매우 느리거나 응답하지 않는 상태를 만든다 (대형 모델 로딩, GPU 과부하, Ollama 내부 행 등)
2. Ollama를 사용하는 API(OCR, 채팅, 번역 등)를 4회 이상 동시에 호출한다
3. 이후 `/health`를 포함한 모든 엔드포인트가 응답하지 않음 (curl 타임아웃)

📸 참고 자료
---

`logs/nssm-stderr.log` (2026-07-19):

```
17:01:06 [INFO] Ollama chat (model=gemma3:4b-it-qat, format=schema)
17:01:06 [WARNING] Task queue depth is 1
17:01:10 [WARNING] Task queue depth is 2
... (계속 증가)
17:11:36 [WARNING] Task queue depth is 38
```

- netstat 확인 결과 포트 5000에 CLOSE_WAIT 소켓 다수 누적 (서버가 소켓을 처리하지 못함)
- Ollama 프로세스와 API(`/api/version`)는 정상 응답 중이었음 (GPU 47% 사용)

✅ 예상 동작
---

- Ollama 호출이 일정 시간 안에 응답하지 않으면 해당 요청만 타임아웃 에러로 실패해야 함
- Ollama가 느려져도 Ollama와 무관한 엔드포인트(`/health`, 팰월드 관리 등)는 정상 응답해야 함

⚙️ 환경 정보
---

- **OS**: Windows 10 (SUH AI 서버, RTX 4060)
- **실행 환경**: NSSM 서비스 `FlaskOCRService` (waitress, threads=4)
- **관련 파일**:
  - `suh-ai-server/flask/service/ollama_service.py` (Client 생성 시 타임아웃 미설정)
  - `suh-ai-server/flask/run.py` (waitress threads=4)

🙋‍♂️ 담당자
---

- **백엔드**: Cassiiopeia
