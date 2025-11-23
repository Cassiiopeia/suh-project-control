# Flask Ollama OCR API

PowerShell OCR 스크립트를 Flask REST API로 구현한 서비스입니다.

## 🚀 Quick Start

### 1. 의존성 설치
```powershell
cd c:\AI\github\suh-project-control\suh-ai-server\flask
python -m pip install -r requirements.txt
```

### 2. 서버 실행

**개발 모드:**
```powershell
python app.py
```

**Production 모드:**
```powershell
python run.py
```

## 📡 API Endpoints

### Health Check
```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "ollama-ocr-api"
}
```

### OCR 수행
```http
POST /ocr
Content-Type: application/json

{
  "image_url": "https://example.com/image.jpg",
  "prompt": "Extract all text from this image",
  "model": "deepseek-ocr"
}
```

**또는 Base64:**
```json
{
  "image_base64": "base64_encoded_string",
  "prompt": "Extract all text",
  "model": "deepseek-ocr"
}
```

**Response:**
```json
{
  "success": true,
  "result": "Extracted text content...",
  "model": "deepseek-ocr",
  "prompt": "Extract all text from this image"
}
```

## 🧪 테스트 방법

### PowerShell에서 테스트
```powershell
# 서버 실행 후
.\test_ocr.ps1
```

## 📁 파일 구조
```
flask/
├── app.py                  # Flask 애플리케이션
├── ocr_service.py          # OCR 로직
├── run.py                  # Production 서버
├── requirements.txt        # Python 의존성
├── test_ocr.ps1            # 테스트 스크립트
├── README.md               # 이 문서
└── logs/                   # 로그 디렉토리 (자동 생성)
    └── flask_ocr.log
```

## 🔧 Windows 서비스 등록

### NSSM 사용
```powershell
# Python 경로 확인
$pythonExe = (Get-Command python).Source
$runScript = "C:\AI\github\suh-project-control\suh-ai-server\flask\run.py"

# 서비스 설치
nssm install FlaskOCRService $pythonExe $runScript

# 설정
nssm set FlaskOCRService AppDirectory "C:\AI\github\suh-project-control\suh-ai-server\flask"
nssm set FlaskOCRService DisplayName "Flask Ollama OCR API"
nssm set FlaskOCRService Start SERVICE_AUTO_START

# 로그 설정
nssm set FlaskOCRService AppStdout "C:\AI\github\suh-project-control\suh-ai-server\flask\logs\service_stdout.log"
nssm set FlaskOCRService AppStderr "C:\AI\github\suh-project-control\suh-ai-server\flask\logs\service_stderr.log"

# 시작
Start-Service FlaskOCRService
```

## 📊 로그 확인

```powershell
# 애플리케이션 로그
Get-Content logs\flask_ocr.log -Tail 50 -Wait
```
