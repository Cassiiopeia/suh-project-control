### 📌 작업 개요

Flask OCR API에서 Ollama 연결 실패로 500 에러가 발생하는 문제 수정. `OLLAMA_HOST` 환경변수가 `0.0.0.0:11434`로 설정되어 있어 ollama Python SDK가 Windows에서 접속 불가능한 주소로 연결을 시도하던 문제를 해결

**보고서 파일**: `.report/20260213_#38_OLLAMA_HOST_환경변수_OCR_API_500에러_수정.md`

### 🔍 문제 분석

`OLLAMA_HOST` 환경변수가 사용자 환경변수에 `0.0.0.0:11434`로 설정되어 있었음. 이 값은 Ollama 서버가 모든 네트워크 인터페이스에서 리스닝하도록 하는 용도로 설정한 것이지만, ollama Python SDK(v0.6.1)도 동일한 환경변수를 읽어 `http://0.0.0.0:11434`로 클라이언트 접속을 시도

- `0.0.0.0`은 서버 리스닝 주소로는 유효하지만, Windows에서 클라이언트 접속 대상으로는 사용 불가 (`WinError 10049`)
- Ollama 프로세스 자체는 정상 실행 중이었고, `httpx`로 `127.0.0.1:11434`에 직접 요청하면 정상 응답 확인
- `FlaskOCRService`가 NSSM을 통해 `LocalSystem` 계정으로 실행 중이어서, 사용자 세션의 Ollama 프로세스와의 연결 컨텍스트도 영향

**에러 로그**:
```
[ERROR] Ollama OCR failed: Failed to connect to Ollama. Please check that Ollama is downloaded, running and accessible.
```

**디버깅 과정**:
1. `tasklist` - Ollama 프로세스 실행 중 확인 (PID 2932)
2. `Invoke-WebRequest localhost:11434` - Ollama 서버 응답 정상 확인
3. `netstat -ano | Select-String 11434` - 포트 리스닝 확인
4. `httpx.get('http://0.0.0.0:11434')` - Windows에서 접속 실패 확인 (`WinError 10049`)
5. `httpx.get('http://127.0.0.1:11434')` - 정상 접속 확인
6. 환경변수 `OLLAMA_HOST=0.0.0.0:11434` 확인 → 근본 원인 특정

### ✅ 구현 내용

#### Ollama Client 명시적 생성으로 변경
- **파일**: `suh-ai-server/flask/service/ocr_service.py`
- **변경 내용**: 모듈 레벨 `chat()` 함수 대신 명시적 `Client(host='http://127.0.0.1:11434')` 인스턴스를 생성하여 사용
- **이유**: 환경변수 `OLLAMA_HOST`에 의존하지 않고, 항상 접속 가능한 `127.0.0.1` 주소를 사용하도록 변경

### 🔧 주요 변경사항 상세

#### ocr_service.py

**import 변경**:
- `from ollama import chat, ChatResponse` → `from ollama import Client, ChatResponse`
- 모듈 레벨 `chat()` 함수 대신 `Client` 클래스 사용

**`__init__` 메서드 수정**:
- 기본 URL을 `http://localhost:11434` → `http://127.0.0.1:11434`로 변경
- `self.client = Client(host=self.ollama_url)` 인스턴스 생성 추가
- 환경변수와 무관하게 항상 명시적 주소로 접속

**`perform_ocr` 메서드 수정**:
- `chat(model=...)` → `self.client.chat(model=...)` 로 변경
- 로그 메시지에 접속 URL 정보 추가: `Sending to Ollama ({model}) at {self.ollama_url}...`

**특이사항**:
- `OLLAMA_HOST=0.0.0.0:11434` 환경변수는 변경하지 않음. Ollama 서버가 외부에서도 접속 가능하도록 리스닝하는 용도로 여전히 필요
- SDK 클라이언트만 명시적 주소를 사용하도록 분리하여 서버 리스닝과 클라이언트 접속 주소의 충돌 해소

### 🧪 테스트 및 검증

- 로컬 테스트: `http://localhost:5000/ocr/base64` → Status 200, glm-ocr 모델 정상 응답
- 외부 테스트: `https://ai.suhsaechan.kr/api/flask/ocr/upload` → Status 200, 정상 동작 확인
- NSSM 서비스 재기동 후에도 정상 동작 확인

### 📌 참고사항

- `OLLAMA_HOST` 환경변수는 Ollama 서버와 SDK 클라이언트 양쪽에서 읽히므로, `0.0.0.0` 같은 리스닝 전용 주소 설정 시 Windows 환경에서 충돌 발생 가능
- 향후 다른 서비스에서도 Ollama SDK를 사용할 경우 동일한 패턴(명시적 Client 생성)을 적용해야 함
