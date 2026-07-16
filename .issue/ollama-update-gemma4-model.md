⚙️ [기능개선][AI서버] Ollama 버전 업데이트 및 gemma4 모델 다운로드
===

📝 현재 문제점
---

- `gemma4:e4b` 모델 pull 시 **412 오류** 발생
  ```
  오류: pull model manifest: 412: The model you are attempting to pull requires 
  a newer version of Ollama. Please download the latest version at: https://ollama.com/download
  ```
- 현재 설치된 Ollama 버전이 낮아 최신 gemma4 모델을 지원하지 못함
- 다운로드 필요 모델:
  - `gemma4:e2b` (7.2GB / 128K / Text, Image)
  - `gemma4:e4b` (9.6GB / 128K / Text, Image)

🛠️ 해결 방안 / 제안 기능
---

- [ ] Ollama를 최신 버전으로 업데이트
- [ ] `gemma4:e2b` 모델 다운로드 (`ollama pull gemma4:e2b`)
- [ ] `gemma4:e4b` 모델 다운로드 (`ollama pull gemma4:e4b`)
- [ ] 기존 OCR 서비스 연동 테스트 확인

⚙️ 작업 내용
---

- Ollama 최신 버전 설치 (https://ollama.com/download)
- gemma4 모델 2종 pull
- 관련 파일 확인:
  - `suh-ai-server/scripts/startup.bat` — Ollama 실행 경로
  - `suh-ai-server/flask/service/ocr_service.py` — Ollama 연동 서비스
  - `suh-ai-server/flask/requirements.txt` — ollama 패키지 (`ollama==0.6.1`)
  - `suh-ai-server/config/nginx.conf` — ollama_backend 프록시 설정
- 필요 시 `ollama` Python 패키지 버전도 함께 업데이트 검토

🙋‍♂️ 담당자
---

- 백엔드: 
