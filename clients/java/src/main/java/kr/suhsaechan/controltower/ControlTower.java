package kr.suhsaechan.controltower;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 관제소 알림 허브 정적 진입점 (서버 전용, 의존성 없음): init > notify / notifyAsync
 * 기본 클라이언트 1개를 공유, init을 다시 호출하면 교체
 */
public final class ControlTower {

    private static final AtomicReference<ControlTowerClient> DEFAULT_CLIENT = new AtomicReference<>();

    private ControlTower() {
    }

    /** 기본 클라이언트 설정 (설정이 잘못되면 IllegalArgumentException) */
    public static ControlTowerClient init(ControlTowerOptions options) {
        ControlTowerClient client = new ControlTowerClient(options);
        DEFAULT_CLIENT.set(client);
        return client;
    }

    /** 기본 baseUrl·timeout으로 설정 */
    public static ControlTowerClient init(String project, String token) {
        return init(ControlTowerOptions.builder().project(project).token(token).build());
    }

    /** 기본 클라이언트로 전송 (init 전이면 not_initialized 결과) */
    public static NotifyResult notify(ControlTowerEvent event) {
        ControlTowerClient client = DEFAULT_CLIENT.get();
        if (client == null) {
            return NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_NOT_INITIALIZED);
        }
        return client.notify(event);
    }

    /** 기본 클라이언트로 비동기 전송 (init 전이면 not_initialized로 완료된 future) */
    public static CompletableFuture<NotifyResult> notifyAsync(ControlTowerEvent event) {
        ControlTowerClient client = DEFAULT_CLIENT.get();
        if (client == null) {
            return CompletableFuture.completedFuture(
                    NotifyResult.failedBeforeResponse(NotifyResult.ERROR_CODE_NOT_INITIALIZED));
        }
        return client.notifyAsync(event);
    }

    /** 기본 클라이언트 해제 (테스트 전용) */
    static void resetForTest() {
        DEFAULT_CLIENT.set(null);
    }
}
