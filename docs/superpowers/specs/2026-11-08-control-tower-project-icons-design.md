# 관제소: 상태 페이지 프로젝트 썸네일 표시와 관리 (#173)

## 왜
- 공개 상태 페이지에서 프로젝트 묶음이 접혀 있어 서비스별 상태를 보려면 눌러야 했음. githubstatus.com처럼 한눈에 보이길 원함.
- 프로젝트마다 아이콘이 있는데 페이지에 없고, 바꿀 방법도 없음.
- 상태 페이지는 집 서버·NAS가 내려가도 보여야 하므로 이미지를 외부 주소(lab 사이트 포함)에서 직접 불러오면 장애 때 깨짐.

## 결정 (소유자 확정)
- 저장·관리: 관리 화면에서 **파일 업로드** 또는 **이미지 주소 가져오기**, 서버가 128px 정사각 WebP로 줄여 저장.
- 이미지 없는 프로젝트: **이름 첫 글자 타일** (프로젝트 id로 색 고정).
- 기본 이미지: `suhsaechan.kr`과 `SUH AI 서버`는 lab.suhsaechan.kr 사이트 로고(`logo_no_text.png`), elum·passql·pickerpicker·bagel은 lab의 프로젝트 로고. 롬롬 등은 관리 화면에서 올림.
- 묶음은 기본 펼침 (`<details open>`, 접기는 유지).

## 데이터 흐름
```
관리 화면 > PUT /control/projects/<id>/icon > Flask SQLite project_icon (128px WebP + 해시 12자)
  > 스냅샷 projects[].icon_version (해시) > 스냅샷 버전 변경
  > 심박: need_config 응답 때 config + project_icons({id: base64}) 동봉
  > Worker D1 meta project_icons_json 전체 교체
  > GET /project-icons/<id>.webp?v=<icon_version> (1년 immutable 캐시)
```
- 이미지가 Cloudflare에 있어 집 서버가 내려가도 유지. CSP `img-src 'self' data:` 변경 없음.
- 관리 화면 미리보기는 API 키 헤더를 이미지 요청에 붙일 수 없어 `/control/manage` 응답에 data URL로 실음.

## 계약
- 관리 API: `PUT /control/projects/<id>/icon` 본문 `{image_base64}` 또는 `{source_url}` 중 하나, `DELETE /control/projects/<id>/icon`. 오류 `invalid_image` 400, `image_too_large` 413, `icon_fetch_failed` 502, `unknown_project`·`no_icon` 404.
- 주소 가져오기: https만, 호스트가 풀리는 모든 주소가 공인 주소일 때만, 리다이렉트 3회까지 매 단계 재검사, 본문 2MB 상한, 응답 시간 8초.
- 이미지 검증: PNG·JPEG·WebP·GIF·ICO, 2,500만 화소 이하, 결과 WebP 30KB 이하(품질을 낮춰 맞춤).
- 등록 파일 `projects[].icon_source_url`(https): 저장된 썸네일이 없는 프로젝트에 한해 기동 때 1회 가져옴. 가져오기 완료 표시를 남겨 관리 화면에서 삭제해도 다시 채우지 않음. 실패는 표시를 남기지 않아 다음 기동에 재시도.
- 심박 본문 상한 256KB > 1MB. `project_icons`는 `config`와 함께 올 때만 저장하며, 없으면 기존 썸네일 유지.

## 하지 않는 것
- SVG 지원, 애니메이션 GIF 유지(첫 프레임만 사용)
- 썸네일 자동 수집(파비콘 크롤링)
- 이미지 크기·품질 설정 화면
