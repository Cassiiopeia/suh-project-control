📝 현재 문제점
---

- `suh-ai-server`는 현재 OCR(텍스트 추출) 기능만 지원하며, 이미지 내용을 자연어로 설명하는 Vision 기능이 없음
- 로컬 ollama에 설치된 vision 지원 모델(`gemma3:4b`, `minicpm-v4.6`, `llava:7b` 등)을 활용한 이미지 설명 API가 부재함
- OCR과 Vision은 용도(텍스트 추출 vs 이미지 설명)와 적합 모델이 달라 별도 엔드포인트로 분리 필요

🛠️ 해결 방안 / 제안 기능
---

- `flask/model/vision_model.py` 신규 추가 — Vision Request/Response 데이터클래스 정의
- `flask/service/vision_service.py` 신규 추가 — Ollama SDK 활용 이미지 설명 비즈니스 로직
- `flask/router/vision_router.py` 신규 추가 — `/vision/url`, `/vision/base64`, `/vision/upload`, `/vision` 엔드포인트
- `flask/config/app_config.py` 수정 — Vision 기본 모델(`gemma3:4b`) 및 지원 모델 목록 추가
- `flask/app.py` 수정 — `vision_bp` Blueprint 등록

⚙️ 작업 내용
---

- Vision 지원 모델 테스트 결과 기반 모델 목록 확정 (gemma3:4b 기본값)
- OCR과 동일한 구조(url/base64/upload/통합)로 Vision 엔드포인트 4개 구현
- 기본 프롬프트: `이 이미지에 대해 한국어로 자세히 설명해줘. 무엇이 보이는지, 분위기, 중요한 디테일까지 알려줘.`

🙋‍♂️ 담당자
---

- 백엔드: Cassiiopeia
