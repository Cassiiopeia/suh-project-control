# AI Server Manager v2.0

깔끔하고 직관적인 AI 서버 관리 시스템입니다.

## 📁 폴더 구조

```
suh-ai-server/
├── start-server.bat          # 🚀 메인 시작 스크립트
├── nginx.conf               # Nginx 설정 파일
├── README.md               # 이 파일
├── scripts/                # 📜 실행 스크립트들
│   ├── start-ollama.bat    # Ollama 서버 시작
│   ├── start-nginx.bat     # Nginx 프록시 시작
│   ├── start-tunnel.bat    # Cloudflare 터널 시작
│   ├── stop-services.bat   # 모든 서비스 중지
│   ├── check-status.bat    # 서비스 상태 확인
│   ├── log-utils.bat       # 로그 유틸리티
│   ├── network-check.ps1   # 네트워크 상태 확인
│   └── get-tunnel-info.ps1 # 터널 정보 조회
├── config/                 # ⚙️ 설정 파일들
│   └── server-config.bat   # 서버 설정
├── logs/                   # 📋 로그 파일들
│   ├── server.log          # 메인 로그
│   ├── error.log           # 에러 로그
│   └── tunnel.log          # 터널 로그
└── data/                   # 💾 데이터 파일들
    ├── tunnel_url.txt      # 터널 URL
    └── tunnel_info.json    # 터널 상세 정보
```

## 🚀 빠른 시작

### 1. 서버 시작
```batch
start-server.bat
```

### 2. 개별 서비스 관리
```batch
# Ollama만 시작
scripts\start-ollama.bat

# Nginx만 시작  
scripts\start-nginx.bat

# 터널만 시작
scripts\start-tunnel.bat

# 모든 서비스 중지
scripts\stop-services.bat

# 상태 확인
scripts\check-status.bat
```

### 3. 네트워크 진단
```powershell
# 네트워크 상태 확인
powershell -ExecutionPolicy Bypass -File scripts\network-check.ps1

# 터널 정보 조회
powershell -ExecutionPolicy Bypass -File scripts\get-tunnel-info.ps1
```

## 🔧 설정

### 서버 설정 변경
`config\server-config.bat` 파일을 편집하여 설정을 변경할 수 있습니다:

- 포트 번호
- API 키
- 로그 레벨
- 자동 재시작 옵션

### Nginx 설정 변경
`nginx.conf` 파일을 편집하여 프록시 설정을 변경할 수 있습니다.

## 📋 로그 확인

모든 로그는 `logs/` 폴더에 저장됩니다:

- `server.log`: 메인 서버 로그
- `error.log`: 에러 로그만 별도 저장
- `tunnel.log`: Cloudflare 터널 로그

## 🌐 접속 정보

### 로컬 접속
- Ollama 직접: `http://localhost:11434`
- Nginx 프록시: `http://localhost:11435`

### 외부 접속 (Cloudflare 터널)
- URL: `data\tunnel_url.txt` 파일 확인
- API 키: `X-API-Key: Kimchi123@`

### 사용 예시
```bash
# API 호출 예시
curl -H "X-API-Key: Kimchi123@" [터널URL]/api/tags
```

## 🔍 문제 해결

### 한국어 출력 문제
모든 스크립트에 `chcp 65001` 명령이 포함되어 한국어가 올바르게 출력됩니다.

### 포트 충돌
`scripts\network-check.ps1`를 실행하여 포트 상태를 확인하세요.

### 터널 연결 실패
1. `cloudflared` 설치 확인
2. 인터넷 연결 확인
3. 방화벽 설정 확인

## 📞 지원

문제가 발생하면 다음을 확인하세요:

1. `logs\error.log` 파일
2. `scripts\check-status.bat` 실행 결과
3. `scripts\network-check.ps1` 실행 결과
