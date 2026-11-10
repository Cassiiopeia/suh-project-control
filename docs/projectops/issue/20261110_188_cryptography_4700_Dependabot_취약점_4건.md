🗒️ 설명
---

- #184에서 Claude 로그인 앱 비밀번호 암호화용으로 추가한 `cryptography==47.0.0`(`suh-ai-server/flask/requirements.txt`)에 Dependabot 보안 경고 4건이 열렸다.
  - 높음: OpenSSL 취약 버전 포함 (GHSA-537c-gmf6-5ccf, 48.0.1에서 수정)
  - 높음: PKCS#7 EnvelopedData 복호화 Bleichenbacher 오라클 (GHSA-g6cj-pr64-35w5, 50.0.0에서 수정)
  - 높음: 중복 자체 서명 중간 인증서로 인한 지수 시간 경로 탐색 (GHSA-jwv3-5hgf-82ww, 49.0.0에서 수정)
  - 보통: 와일드카드 DNS 이름 검증 우회 (GHSA-m2h6-j472-rp4c, 49.0.0에서 수정)
- 이 서버가 쓰는 기능은 AES-256-GCM과 PBKDF2뿐이라 인증서 검증·PKCS#7 경로는 직접 쓰지 않지만, 패키지 안의 OpenSSL 취약점은 그대로 영향이 있다.

🔄 재현 방법
---

1. GitHub 저장소 Security > Dependabot alerts 확인
2. `cryptography` 47.0.0 관련 경고 4건 (#69~#72)

📸 참고 자료
---

- Dependabot alerts #69, #70, #71, #72

✅ 예상 동작
---

- `cryptography` 를 50.0.0으로 올려 경고 4건이 모두 해소되어야 한다.
- 앱 비밀번호 암호화·복호화(기존 저장된 암호문 포함)는 그대로 동작해야 한다.

⚙️ 환경 정보
---

- **OS**: Windows 10 (SUH AI 서버, Python 3.13.7)
- **브라우저**: 해당 없음
- **기기**: 해당 없음

🙋‍♂️ 담당자
---

- 오너: Cassiiopeia
