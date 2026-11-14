# Apprise (vendored)

- 원본: https://github.com/caronc/apprise
- 태그: v2.2.0
- 커밋: 58e42d2fc826adcb3be35272df34d3888d061b34
- 라이선스: BSD-2-Clause (같은 폴더 LICENSE)
- 복사 날짜: 2026-11-13
- 복사 범위: 원본 `apprise/` 패키지 폴더 전체 + 최상위 LICENSE (tests, packaging, bin, 문서 제외)
- import 경로: `vendor.apprise`

## 고친 목록

- `manager_plugins.py`, `manager_config.py`, `manager_attachment.py`: `module_name_prefix`를 `f"apprise.{_id}"`에서 `f"{__package__}.{_id}"`로 변경 (플러그인을 `vendor.apprise.plugins.*`로 불러오기 위함)
- `utils/format.py:34`: `from apprise.common import NotifyFormat`를 `from ..common import NotifyFormat`로 변경 (상대 import)

그 외 파일은 원본과 동일. 원본 의존성 중 requirements.txt에 새로 고정한 것: markdown, requests-oauthlib(+oauthlib), click, certifi
