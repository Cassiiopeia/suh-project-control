<!-- projectops:report -->
# ❗[버그][보안] cryptography 47.0.0 Dependabot 취약점 4건

## 개요

#184에서 앱 비밀번호 암호화용으로 추가한 `cryptography==47.0.0`에 열린 Dependabot 보안 경고 4건(높음 3, 보통 1)을 50.0.0으로 올려 해소했다. 4건 중 가장 높은 수정 버전이 50.0.0(PKCS#7 Bleichenbacher)이라 한 번에 맞췄다.

## 변경 사항

- `suh-ai-server/flask/requirements.txt`: `cryptography==47.0.0` > `cryptography==50.0.0`

## 핵심 구현

- 이 서버가 쓰는 API는 `AESGCM`, `PBKDF2HMAC` 두 가지뿐이고 50.0.0에서도 그대로다. 인증서 검증·PKCS#7 경로는 쓰지 않지만, wheel 안에 들어 있는 OpenSSL 취약점(GHSA-537c-gmf6-5ccf)은 버전을 올려야만 해소된다.
- 저장 형식(`salt | nonce | 암호문+태그`)과 키 생성 방식은 라이브러리 버전과 무관하다. 이미 DB에 저장된 암호문은 다시 넣을 필요가 없다.

## 검증

- 호환: 47.0.0으로 암호화한 값을 50.0.0 격리 환경에서 복호화 > 원문 일치
- 50.0.0 격리 환경에서 암호화 테스트 6건 통과
- 배포 후 서버: `cryptography 50.0.0` 설치 확인, 저장된 계정(`chan4760@gmail.com`) 접속 테스트 > 복호화 + Gmail 로그인 성공
- Dependabot 열린 경고 0건

## 주의사항

- 배포 스크립트가 `pip install -r requirements.txt --upgrade` 로 설치하므로, 버전을 바꾸면 다음 배포에서 서버에 그대로 반영된다.
