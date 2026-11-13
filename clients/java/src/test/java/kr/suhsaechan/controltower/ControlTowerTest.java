package kr.suhsaechan.controltower;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 정적 진입점 테스트: init 전 호출, init 후 전송, 비동기 전송
 */
class ControlTowerTest {

    private FakeServer server;

    @AfterEach
    void cleanUp() {
        ControlTower.resetForTest();
        if (server != null) {
            server.close();
        }
    }

    private void initWithServer() throws IOException {
        server = new FakeServer();
        ControlTower.init(ControlTowerOptions.builder()
                .baseUrl(server.baseUrl()).project("suh-ai").token("secret-token-123").build());
    }

    @Test
    void notifyBeforeInitIsNotInitialized() {
        ControlTower.resetForTest();
        assertEquals(new NotifyResult(false, null, "not_initialized", false),
                ControlTower.notify(ControlTowerEvent.of("report", "제목")));
    }

    @Test
    void notifyAsyncBeforeInitIsCompletedNotInitialized() {
        ControlTower.resetForTest();
        var future = ControlTower.notifyAsync(ControlTowerEvent.of("report", "제목"));
        assertTrue(future.isDone());
        assertEquals("not_initialized", future.join().errorCode());
    }

    @Test
    void initAndNotify() throws IOException {
        initWithServer();
        assertTrue(ControlTower.notify(ControlTowerEvent.of("report", "제목")).isAccepted());
    }

    @Test
    void initAndNotifyAsync() throws Exception {
        initWithServer();
        NotifyResult result = ControlTower.notifyAsync(ControlTowerEvent.of("report", "t").severity("warning"))
                .get(5, TimeUnit.SECONDS);
        assertTrue(result.isAccepted());
        Map<?, ?> payload = (Map<?, ?>) JsonValueParser.parse(server.receivedRequests.get(0).bodyText());
        assertEquals("warning", payload.get("severity"));
    }

    @Test
    void initWithProjectAndTokenUsesDefaultBaseUrl() {
        ControlTowerClient client = ControlTower.init("romrom", "token-value");
        assertNotNull(client);
        assertTrue(client.toString().contains("https://ai.suhsaechan.kr/api/flask/control/events"));
    }

    @Test
    void initWithBadConfigurationThrows() {
        assertThrows(IllegalArgumentException.class, () -> ControlTower.init("", "token-value"));
        assertThrows(IllegalArgumentException.class, () -> ControlTower.init((ControlTowerOptions) null));
    }
}
