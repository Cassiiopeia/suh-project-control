package kr.suhsaechan.controltower;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

import java.time.Duration;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 설정 검증 테스트: 잘못된 설정 > IllegalArgumentException (메시지에 토큰 없음)
 */
class ControlTowerOptionsTest {

    /** 잘못된 설정 1건: project, token, baseUrl(null이면 기본값) */
    record BadConfiguration(String project, String token, String baseUrl) {
    }

    static Stream<BadConfiguration> badConfigurations() {
        return Stream.of(
                new BadConfiguration("", "t", null),
                new BadConfiguration(null, "t", null),
                new BadConfiguration("p", "", null),
                new BadConfiguration("p", null, null),
                new BadConfiguration("p", "a b", null),
                new BadConfiguration("p", "a\nb", null),
                new BadConfiguration("p", "a\u007fb", null),
                new BadConfiguration("p", "토큰", null),
                new BadConfiguration("p", "t", "http://example.com"),
                new BadConfiguration("p", "t", "ftp://x"),
                new BadConfiguration("p", "t", "not a url"),
                new BadConfiguration("p", "t", "https://"));
    }

    @ParameterizedTest
    @MethodSource("badConfigurations")
    void badConfigurationThrowsWithoutToken(BadConfiguration configuration) {
        ControlTowerOptions.Builder builder = ControlTowerOptions.builder()
                .project(configuration.project()).token(configuration.token());
        if (configuration.baseUrl() != null) {
            builder.baseUrl(configuration.baseUrl());
        }
        IllegalArgumentException error = assertThrows(IllegalArgumentException.class, builder::build);
        // 설정 오류 메시지에 토큰 값이 들어가지 않음 (길이 있는 토큰만 검사)
        if (configuration.token() != null && configuration.token().length() > 1) {
            assertFalse(error.getMessage().contains(configuration.token()));
        }
    }

    @Test
    void badTimeoutThrows() {
        assertThrows(IllegalArgumentException.class,
                () -> ControlTowerOptions.builder().project("p").token("t").timeout(Duration.ZERO).build());
        assertThrows(IllegalArgumentException.class,
                () -> ControlTowerOptions.builder().project("p").token("t").timeout(null).build());
    }

    @Test
    void httpsAndLocalHttpAccepted() {
        assertDoesNotThrow(() -> ControlTowerOptions.builder().project("p").token("t").build());
        assertDoesNotThrow(() -> ControlTowerOptions.builder().project("p").token("t")
                .baseUrl("http://localhost:8080").build());
        assertDoesNotThrow(() -> ControlTowerOptions.builder().project("p").token("t")
                .baseUrl("http://127.0.0.1:5000/").build());
    }

    @Test
    void defaults() {
        ControlTowerOptions options = ControlTowerOptions.builder().project("p").token("t").build();
        assertEquals("https://ai.suhsaechan.kr/api/flask", options.baseUrl());
        assertEquals(Duration.ofSeconds(3), options.timeout());
    }

    @Test
    void toStringHasNoToken() {
        ControlTowerOptions options = ControlTowerOptions.builder().project("p").token("secret-token-123").build();
        assertFalse(options.toString().contains("secret-token-123"));
        assertFalse(ControlTowerOptions.builder().project("p").token("secret-token-123").toString()
                .contains("secret-token-123"));
    }
}
