# SUH AI Server

Windows 기반 AI 서버 시스템으로 Ollama, Nginx, Cloudflare Tunnel을 통합 관리합니다.

## 📁 프로젝트 구조

```
suh-ai-server/
├── config/                 # 설정 파일
│   ├── nginx.conf         # Nginx 메인 설정 (Lua 지원)
│   ├── nginx-simple.conf  # Nginx 심플 설정 (Lua 미지원)
│   ├── api_keys.txt       # API 키 저장
│   ├── auth_tokens.txt    # Bearer 토큰 저장
│   └── cloudflare-tunnel.yml # Cloudflare 터널 설정
├── logs/                   # 로그 파일
│   ├── nginx.log
│   ├── ollama.log
│   ├── cloudflare.log
│   └── startup_*.log
├── scripts/                # 스크립트
│   ├── start-up-auto.bat  # 자동 시작 스크립트
│   ├── start-cloudflare-tunnel.bat
│   ├── stop-all-services.bat
│   ├── setup-windows-startup.bat
│   └── install-dependencies.bat
├── api/                    # API 도구
│   ├── health-check.ps1   # 헬스 체크
│   └── generate-api-key.ps1 # API 키 생성
└── data/                   # 데이터 파일
    └── tunnel-info.json    # 터널 정보
```

## 🚀 빠른 시작

### 1. 의존성 설치

관리자 권한으로 실행:

```batch
.\scripts\install-dependencies.bat
```

설치되는 패키지:
- Chocolatey (패키지 매니저)
- Nginx (프록시 서버)
- Ollama (AI 모델 서버)
- Cloudflared (터널링)
- Curl (테스트용)

### 2. Cloudflare 터널 설정

1. Cloudflare 계정에서 터널 생성
2. `config\credentials.json` 파일에 인증 정보 저장
3. `config\cloudflare-tunnel.yml` 파일에서 도메인 설정

### 3. API 키 생성

```powershell
# API 키 생성
powershell .\api\generate-api-key.ps1

# Bearer 토큰 생성
powershell .\api\generate-api-key.ps1 -Type bearer_token
```

### 4. Windows 자동 시작 설정

```batch
.\scripts\setup-windows-startup.bat
```

### 5. 서비스 시작

```batch
.\scripts\start-up-auto.bat
```

## 🔌 API 엔드포인트

### 공개 엔드포인트 (인증 불필요)

- `GET /health` - 서버 상태 확인
- `GET /api/tunnel-info` - Cloudflare 터널 정보

### 보호된 엔드포인트 (인증 필요)

- `GET /api/logs` - 로그 목록 조회
- `GET /api/logs/{filename}` - 특정 로그 파일 조회
- `POST /` - Ollama API 프록시

### 인증 방법

1. **Bearer Token**
```http
Authorization: Bearer YOUR_TOKEN_HERE
```

2. **API Key**
```http
X-API-KEY: YOUR_API_KEY_HERE
```

**참고**: 로컬 네트워크(127.0.0.0/8, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12)에서는 인증이 필요하지 않습니다.

## 🛠️ 서비스 관리

### 서비스 상태 확인

```powershell
powershell .\api\health-check.ps1
```

### 서비스 중지

```batch
.\scripts\stop-all-services.bat
```

### 로그 확인

로그 파일은 `logs/` 디렉토리에 저장됩니다:
- `startup_*.log` - 시작 로그
- `nginx.log` - Nginx 로그
- `ollama.log` - Ollama 로그
- `cloudflare.log` - Cloudflare 터널 로그

## 📋 포트 정보

- **11434**: Ollama 서버 (내부)
- **11435**: Nginx 프록시 (외부 접근)

## 🔧 문제 해결

### Nginx가 Lua를 지원하지 않는 경우

`nginx-simple.conf` 파일을 사용하세요:

```batch
nginx -c config\nginx-simple.conf
```

### Cloudflare 터널이 연결되지 않는 경우

1. 인증 정보 확인: `config\credentials.json`
2. 터널 설정 확인: `config\cloudflare-tunnel.yml`
3. 로그 확인: `logs\cloudflare.log`

### Ollama가 시작되지 않는 경우

```batch
# 수동으로 Ollama 시작
ollama serve
```

## 📝 로그 레벨

Nginx 로그 레벨 (nginx.conf에서 설정):
- `debug`, `info`, `notice`, `warn`, `error`, `crit`, `alert`, `emerg`

## 🔐 보안 참고사항

1. API 키와 토큰은 안전하게 보관하세요
2. `config\api_keys.txt`와 `config\auth_tokens.txt` 파일 권한을 제한하세요
3. 운영 환경에서는 HTTPS를 사용하세요
4. 정기적으로 API 키를 교체하세요

## 📚 추가 자료

- [Ollama 문서](https://ollama.ai/docs)
- [Nginx 문서](https://nginx.org/en/docs/)
- [Cloudflare Tunnel 문서](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/)