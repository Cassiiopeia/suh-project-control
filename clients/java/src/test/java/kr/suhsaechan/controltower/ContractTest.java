package kr.suhsaechan.controltower;

import org.junit.jupiter.api.Test;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 계약 테스트: 클라이언트 본문 <-> 레포 예시(valid_custom_kind_fields.json) JSON 비교
 */
class ContractTest {

    private static Path eventsDirectory() {
        // build.gradle이 docs/control-tower/events 절대 경로를 넘김 (IDE 실행 시 상대 경로)
        String configured = System.getProperty("controlTower.eventsDirectory");
        return configured != null ? Path.of(configured) : Path.of("../../docs/control-tower/events");
    }

    @Test
    void requestBodyEqualsExample() throws IOException {
        ControlTowerClient client = new ControlTowerClient(ControlTowerOptions.builder()
                .baseUrl("http://127.0.0.1:1").project("suh-ai").token("t").build());
        String requestBody = client.buildRequestBody(ControlTowerEvent.of("claude-code", "로그인 인증코드 발급")
                .severity("info").field("요청 경로", "메일 링크").field("유효 시간", "10분"));
        String example = Files.readString(
                eventsDirectory().resolve("examples/valid_custom_kind_fields.json"), StandardCharsets.UTF_8);
        assertEquals(JsonValueParser.parse(example), JsonValueParser.parse(requestBody));
    }
}
