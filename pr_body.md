<!-- This is an auto-generated comment: release notes by coderabbit.ai -->

## Summary by CodeRabbit

## 릴리스 노트

### 새 기능
- 관리 페이지가 추가되었습니다. 이제 `/admin/tts` 경로에서 TTS 엔진을 관리할 수 있습니다.
- `/tts` 경로에 합성 및 엔진 제어 API가 추가되었으며, 감사 로그 기능이 포함되었습니다.
- Docker CLI 기반의 엔진 수명주기 서비스가 추가되었습니다. 이를 통해 엔진 관리가 더욱 용이해졌습니다.
- Kokoro와 CosyVoice 어댑터가 추가되어 다양한 음성 서비스를 지원합니다.
- 엔진 레지스트리 및 레퍼런스 음성 자산이 추가되어 더 풍부한 음성 합성이 가능합니다.

### 버그 수정
- CosyVoice의 이미지 빌드 실패가 수정되었습니다. 이로 인해 `setuptools<81` 빌드가 격리되어 강제 적용됩니다.

### 개선
- `deploy-tts`를 위한 사전준비 스크립트 및 배포 단계가 추가되어 배포 프로세스가 향상되었습니다.
- CosyVoice 서빙 이미지 및 CI 빌드 워크플로우가 추가되어 더욱 안정적인 지속적 통합 환경이 구축되었습니다.
- Swagger에 TTS API 경로가 추가되어 API 문서화가 개선되었습니다.
- 릴리즈 문서가 업데이트되어 새로운 버전에 대한 정보가 명확하게 제공됩니다.

<!-- end of auto-generated comment: release notes by coderabbit.ai -->
