# suh-control-tower-client (Java)

> **서버 전용 클라이언트입니다. 모바일 앱(Android)에 넣지 마세요.** 프로젝트 토큰이 앱에 들어가면 누구나 꺼낼 수 있습니다.
> 어떤 내용을 보낼지(개인정보 포함 여부)는 보내는 쪽이 판단합니다. 이메일, 전화번호 같은 개인정보는 `title`, `body`, `fields`에 넣지 마세요.

관제소 알림 허브(`POST /control/events`)로 "지금 일어난 일"을 보내는 의존성 없는 Java 클라이언트입니다(Java 17 이상, JDK `java.net.http`만 사용). 규격은 [events 가이드](../../docs/control-tower/events/README.md)가 원본입니다.

좌표: `kr.suhsaechan:suh-control-tower-client:0.1.0` (Spring 자동 설정 없음, 정적 `ControlTower.init`)

## 설치

아직 Maven Central에 게시하지 않았습니다. 소스에서 씁니다.

**방법 1. 로컬 Maven 저장소에 설치**

`build.gradle`에는 게시 설정이 없으므로, 설치할 때만 `maven-publish`를 붙이는 init 스크립트를 씁니다.

```bash
cd clients/java
cat > /tmp/control-tower-local-publish.gradle <<'GRADLE'
allprojects {
    apply plugin: 'maven-publish'
    afterEvaluate {
        publishing { publications { maven(MavenPublication) { from components.java } } }
    }
}
GRADLE
./gradlew publishToMavenLocal --init-script /tmp/control-tower-local-publish.gradle
```

```groovy
// 사용하는 프로젝트의 build.gradle
repositories { mavenLocal(); mavenCentral() }
dependencies { implementation 'kr.suhsaechan:suh-control-tower-client:0.1.0' }
```

**방법 2. Gradle composite build (`includeBuild`)**

```groovy
// 사용하는 프로젝트의 settings.gradle
includeBuild('../suh-project-control/clients/java')
```

```groovy
// 사용하는 프로젝트의 build.gradle (좌표가 includeBuild 소스로 대체됨)
dependencies { implementation 'kr.suhsaechan:suh-control-tower-client:0.1.0' }
```

## 사용

토큰은 관제소 관리 화면(서비스 관리 > 프로젝트 > 이벤트 토큰)에서 발급해 환경변수에 둡니다.

```java
import kr.suhsaechan.controltower.ControlTower;
import kr.suhsaechan.controltower.ControlTowerEvent;
import kr.suhsaechan.controltower.ControlTowerOptions;
import kr.suhsaechan.controltower.NotifyResult;

// 앱 시작 시 한 번 (project, token 필수)
ControlTower.init(ControlTowerOptions.builder()
        .project("my-project")
        .token(System.getenv("CONTROL_TOWER_TOKEN"))   // 교체 시 환경변수만 바꾸고 재시작
        // .baseUrl(...)  기본값: https://ai.suhsaechan.kr/api/flask
        // .timeout(...)  기본값: Duration.ofSeconds(3)
        .build());
// 기본값만 쓰면: ControlTower.init("my-project", System.getenv("CONTROL_TOWER_TOKEN"));

NotifyResult result = ControlTower.notify(ControlTowerEvent.of("error", "결제 실패")
        .severity("critical")
        .body("결제 승인 응답 지연")
        .url("https://example.com/orders/42")
        .field("주문", 42)                   // 넣은 순서 유지, 값은 String.valueOf로 문자열화 (42 > "42", true > "true")
        .field("원인", "timeout")            // 여러 개는 .fields(LinkedHashMap)도 가능
        .dedupeKey("payment-error:42"));
```

필드 값은 모두 문자열로 보냅니다. boolean 값은 `"true"`/`"false"`가 되므로 "예/아니오"처럼 읽기 쉬운 값이 필요하면 직접 바꿔 넣으세요. 빈 Map을 `.fields(...)`에 넘기면 `"fields": []`로 보냅니다.

`ControlTower` 정적 진입점 대신 `new ControlTowerClient(options)`를 직접 만들어 써도 됩니다(스레드 안전).

- 설정 오류는 `build()`/`init`에서 `IllegalArgumentException`으로 알립니다: 빈 `project`/`token`, 공백·제어문자·비ASCII가 든 토큰, `https`가 아닌 `baseUrl`(테스트용 `http://127.0.0.1`, `http://localhost`만 예외), 0 이하 `timeout`. 앱 시작 시 한 번 걸러집니다. 메시지에 토큰은 들어가지 않습니다.
- `notify`/`notifyAsync`는 예외를 던지지 않습니다.
- `timeout`은 **요청 전체 소요 시간 상한**입니다(연결 + 응답 헤더 + 응답 본문까지, 넘으면 전송을 취소하고 `timeout`). Python 클라이언트의 `timeout_seconds`는 소켓 동작마다 적용되는 값이라 의미가 조금 다릅니다.
- 리다이렉트(3xx)는 따라가지 않습니다(토큰 유출 방지). 결과는 `http_302`처럼 실제 상태로 나옵니다.

### Spring 서비스 안에서

알림 때문에 응답이 늦어지지 않도록 `notifyAsync`를 씁니다. 즉시 `CompletableFuture<NotifyResult>`를 돌려주고, 실패해도 예외로 완료되지 않고 결과로 완료됩니다(`init` 전에 호출하면 `not_initialized`로 이미 완료된 future). 전송은 JDK `HttpClient`의 데몬 스레드에서 진행되므로 프로세스가 종료되면 진행 중이던 전송은 버려집니다.

```java
@Configuration
class ControlTowerConfiguration {
    ControlTowerConfiguration(@Value("${control-tower.token}") String token) {
        ControlTower.init("my-project", token);   // 앱 시작 시 한 번
    }
}

@Service
@Slf4j
@RequiredArgsConstructor
public class ReportService {

    public Report createReport(ReportRequest request) {
        Report report = ...;
        ControlTower.notifyAsync(ControlTowerEvent.of("report", "신고 접수")
                        .field("신고 번호", report.getId())
                        .dedupeKey("report:" + report.getId()))
                .thenAccept(result -> {
                    if (!result.isAccepted()) {
                        log.warn("[control-tower client] not delivered : {}", result.errorCode());
                    }
                });
        return report;
    }
}
```

## 결과 처리

`notify`는 예외를 던지지 않고 `NotifyResult` record를 돌려줍니다.

| 필드 | 뜻 |
|---|---|
| `isAccepted()` | 서버가 접수(202)했는지 |
| `statusCode()` | HTTP 상태 (`Integer`, 네트워크 오류, 시간 초과, init 전, 로컬 검증 실패는 `null`) |
| `errorCode()` | 서버 `error` 값(`invalid`, `unknown_kind`, `unauthorized`, `unknown_project`, `unavailable`), JSON이 아닌 응답은 `http_<상태>`(예 `http_413`), `timeout`, `connection_error`, `not_initialized`, `invalid_input`(보내기 전 로컬 검증 실패, 예 필드 이름이나 값이 `null`. 서버의 `invalid`와 구분) |
| `isDeduplicated()` | `dedupeKey` 중복으로 알림 없이 접수만 됨 |

```java
if (!result.isAccepted()) {
    log.warn("[control-tower client] not delivered : {}", result.errorCode());
}
```

코드 문자열은 `NotifyResult.ERROR_CODE_TIMEOUT` 같은 상수로도 비교할 수 있습니다. `unavailable`, `timeout`, `connection_error`는 잠시 뒤 같은 `dedupeKey`로 재시도할 수 있습니다. 토큰은 로그, `toString`, 예외 메시지에 넣지 않습니다.

## 개발

```bash
cd clients/java
./gradlew test build    # 로컬 127.0.0.1 테스트 서버만 사용, 계약 테스트는 docs/control-tower/events/examples와 비교
```
