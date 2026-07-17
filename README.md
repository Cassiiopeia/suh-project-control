# 🧠 SUH-PROJECT-CONTROL
<!-- 수정하지마세요 자동으로 동기화 됩니다 -->
<!-- AUTO-VERSION-SECTION: DO NOT EDIT MANUALLY -->
## 최신 버전 : v2.0.36 (2026-07-17)

[전체 버전 기록 보기](CHANGELOG.md)
---

<div align="center">

**개인 GPU 서버에서 AI API 서빙과 팰월드 서버 운영을 함께 처리하는 홈서버 프로젝트**

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
![Ollama](https://img.shields.io/badge/Ollama-000000?style=for-the-badge&logo=ollama&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Windows](https://img.shields.io/badge/Windows%20Server-0078D4?style=for-the-badge&logo=windows&logoColor=white)
![Palworld](https://img.shields.io/badge/Palworld-Dedicated%20Server-2ea44f?style=for-the-badge&logo=steam&logoColor=white)

</div>

---

## 📖 소개

개인 GPU 서버(AI 서버)를 운영하기 위한 프로젝트입니다.

서버에는 Ollama가 상시 구동되고 있어 로컬 모델 기반 OCR·비전 API를 제공하고,
남는 리소스로 팰월드 데디케이티드 서버를 함께 호스팅합니다.

게임 서버를 올리면 재시작, 설정 수정, 업데이트, 백업 같은 관리 작업이 계속 생기는데,
이걸 매번 서버에 접속해서 처리하는 대신 웹 대시보드와 REST API로 처리할 수 있게 만들었습니다.

## ✨ 핵심 특징

- **🤖 로컬 AI API**: Ollama 기반 OCR(deepseek-ocr)·이미지 분석(Vision) REST API — URL/Base64/파일 업로드 모두 지원
- **🎮 팰월드 원격 관리**: 브라우저에서 서버 시작/중지/재시작, 실시간 상태 확인
- **📈 실시간 메트릭 그래프**: 서버 FPS·프레임타임·접속자 수를 시계열로 적재해 추이 시각화
- **⚙️ 안전한 월드 설정 편집**: `PalWorldSettings.ini`를 웹에서 수정 — 서버 가동 중엔 편집을 차단해 설정 유실 방지
- **🔄 SteamCMD 자동 업데이트**: 새 빌드 자동 감지 → 백업 → 중지 → 업데이트 → 재시작까지 원클릭, 진행 로그 실시간 스트리밍
- **💾 세이브 백업**: 월드 세이브 백업 생성·목록 관리
- **📜 감사로그(Audit Log)**: 누가 언제 어떤 관리 행위를 했는지 PostgreSQL에 기록 — DB가 죽어도 관리 기능은 막히지 않는 fail-open 설계
- **🚀 풀 자동화 CI/CD**: 버전 관리·CHANGELOG·릴리즈가 GitHub Actions로 전부 자동

## 🤖 AI API

GPU에서 도는 Ollama 모델을 REST로 바로 씁니다. Swagger UI로 문서화되어 있습니다.

| 엔드포인트 | 설명 |
|---|---|
| `POST /ocr` `/ocr/url` `/ocr/base64` `/ocr/upload` | 이미지에서 텍스트 추출 (deepseek-ocr) |
| `POST /vision` `/vision/url` `/vision/base64` `/vision/upload` | 비전 모델 이미지 분석·설명 |
| `GET /logs` `/logs/stream` | 서버 로그 조회·실시간 스트리밍 |
| `GET /health` | 헬스체크 (배포 스크립트·대시보드 연동) |

## 🎮 팰월드 관리자

관리자 대시보드(`/admin/palworld`)에서 게임 서버 운영의 전부를 처리합니다.

| 기능 | 내용 |
|---|---|
| 서비스 제어 | NSSM 윈도우 서비스 시작/중지/재시작 + 팰월드 공식 REST API 중계 |
| 메트릭 히스토리 | FPS·평균 FPS·프레임타임·접속자·게임 내 일수 시계열 그래프 (링버퍼 + jsonl 영속화로 재기동에도 유지) |
| 월드 설정 | 웹에서 `PalWorldSettings.ini` 편집 — 가동 중 수정은 차단 (종료 시 덮어써져 유실되는 문제 원천 봉쇄) |
| 업데이트 | SteamCMD `app_info`로 새 빌드 자동 감지, 배지 알림 → 원클릭 업데이트 (백업→중지→다운로드→시작), 진행 패널 실시간 표시 |
| 백업 | 월드 세이브 백업 생성·목록 조회 |
| 접속 가이드 | 같이 할 사람에게 보여줄 접속 안내 페이지 제공 |
| 감사로그 | 모든 관리 행위를 PostgreSQL에 기록·조회 |

## 🛠️ 기술 스택

| 영역 | 스택 |
|---|---|
| 백엔드 | Python · Flask · flask-swagger-ui |
| AI 추론 | Ollama (deepseek-ocr, 비전 모델) — 전부 로컬 GPU |
| 게임 서버 | Palworld Dedicated Server · SteamCMD · NSSM |
| 데이터 | PostgreSQL (감사로그) · jsonl 링버퍼 (메트릭) |
| 프론트 | Jinja2 + Tailwind CSS (daisyUI) |
| 인프라 | Windows Server · GitHub Actions CI/CD |

