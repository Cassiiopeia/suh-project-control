# 관제소 서비스 위치 표

2026-11-07 실측 (NAS DSM 역방향 프록시 규칙 읽기 + SUH AI 서버에서 포트 응답 확인).
IP는 적지 않음: NAS 내부 IP는 `NAS_LAN_HOST`, AI 서버 내부 IP는 NAS 프록시 규칙에만 있음.
이 표가 `suh-ai-server/flask/config/control_tower/services.yml`의 `internal` 점검과 `depends_on`의 근거.

## 네트워크 구조

- 공유기 DMZ > NAS. NAS 역방향 프록시(443)가 도메인별로 NAS 컨테이너 포트 또는 AI 서버로 넘김.
- DNS·기본 게이트웨이는 NAS를 거치지 않음 (NAS도 공유기 게이트웨이·통신사 DNS 사용).
- `ai.suhsaechan.kr` > NAS 프록시 > AI 서버 nginx `:11435` > Flask `:5000` / Ollama `:11434`.
  NAS가 죽으면 AI 서버 공개 주소도 함께 끊김. 관제소 심박(AI 서버 > Worker)은 NAS와 무관.

## 도메인 > 백엔드 (NAS 프록시 규칙)

| 도메인 | 백엔드 | 내부 점검 | 비고 |
|---|---|---|---|
| ai.suhsaechan.kr | AI 서버 `:11435` | 없음 | 관제소 자신, 심박으로 판정 |
| web.suhsaechan.kr | NAS `:3007` (https) | tcp | 자체 서명 인증서라 tcp만 |
| chrome.suhsaechan.kr | NAS `:3008` (https) | tcp | 위와 같음 |
| pickerpicker.suhsaechan.kr | NAS `:3010` | http | |
| api.pickerpicker.suhsaechan.kr | NAS `:8001` | http | 401 응답 = 정상 |
| bagel.suhsaechan.kr | NAS `:3006` | http | |
| api.bagel.suhsaechan.kr | NAS `:8093` | http | 루트 500 응답 = 정상 (502·503·504만 장애) |
| palim.suhsaechan.kr | NAS `:8095` | http | |
| api.mapsy.suhsaechan.kr | NAS `:8096` | http | hack-the-beat API와 같은 포트 |
| api.hack-the-beat.suhsaechan.kr | NAS `:8096` | http | |
| api.elum · api.passql · ai.passql · api.romrom · lab | NAS `:8079` | 없음 | 공용 진입 포트(Host로 분기), 포트 응답만으로 서비스 구분 불가 |
| mongo · pgadmin · rabbitmq · minio · qdrant · nexus · traefik · s3 | NAS `:8081` `:5050` `:15672` `:9090` `:6333` `:9999` `:8078` `:9000` | http | infra 프로젝트, 비공개 |
| admin.romrom · ai.mapsy · ai.tripgether · api.tripgether · api.test.tripgether · api.sejong-malsami · sejong-malsami · api.spacestudyship · romi | NAS `:3005` `:8092` `:8091` `:8088` `:8089` `:8087` `:3004` `:8099` `:8083` | 없음 | 포트 무응답, 등록 파일에서 `paused` |
| DSM | NAS `:5001` | tcp | 인프라 `nas` 점검 |

프록시 규칙에 없는 도메인(suhsaechan.kr, www, note, file, mail, chat.suhsaechan.kr, romrom, freemates.suhsaechan.kr, server, lab.beta)은 DSM 포털·Web Station 등 다른 경로라 외부 점검만 둠.

## 다시 확인하는 법

- NAS: `/etc/nginx/sites-enabled/server.ReverseProxy.conf`의 `server_name`·`proxy_pass` (읽기 전용)
- AI 서버에서 포트 응답: `curl.exe -s -o NUL -w "%{http_code}" http://<NAS_LAN_HOST>:<포트>/`
