package kr.suhsaechan.controltower;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * JSON 작성 테스트: 이스케이프 (따옴표, 역슬래시, 제어문자, 줄 구분자, 한글, 이모지)
 */
class EventJsonWriterTest {

    private static String write(String text) {
        return EventJsonWriter.write(text);
    }

    @Test
    void escapesQuoteAndBackslash() {
        assertEquals("\"a\\\"b\\\\c\"", write("a\"b\\c"));
    }

    @Test
    void escapesControlCharacters() {
        assertEquals("\"\\n\\r\\t\\b\\f\\u0001\\u001f\"", write("\n\r\t\b\f\u0001\u001f"));
    }

    @Test
    void escapesLineSeparators() {
        assertEquals("\"\\u2028\\u2029\"", write("\u2028\u2029"));
    }

    @Test
    void keepsKoreanAndEmojiAsIs() {
        assertEquals("\"한글 😀\"", write("한글 😀"));
    }

    @Test
    void rejectsLoneSurrogate() {
        assertThrows(IllegalArgumentException.class, () -> write("a\ud83d"));
        assertThrows(IllegalArgumentException.class, () -> write("\ude00b"));
    }

    @Test
    void writesNestedStructureInOrder() {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("z", "1");
        payload.put("a", List.of(Map.of("name", "n")));
        payload.put("flag", true);
        payload.put("none", null);
        assertEquals("{\"z\":\"1\",\"a\":[{\"name\":\"n\"}],\"flag\":true,\"none\":null}",
                EventJsonWriter.write(payload));
    }

    @Test
    void roundTripsThroughParser() {
        String text = "따옴표\" 역슬래시\\ 줄\n 제어\u0002 구분\u2028 이모지😀";
        assertEquals(text, JsonValueParser.parse(EventJsonWriter.write(text)));
    }

    @Test
    void parserRejectsDeepNestingWithoutStackOverflow() {
        assertThrows(IllegalArgumentException.class, () -> JsonValueParser.parse("[".repeat(100_000)));
        assertEquals(List.of(List.of()), JsonValueParser.parse("[[]]"));
    }

    @Test
    void parserRejectsSignedHexInUnicodeEscape() {
        assertThrows(IllegalArgumentException.class, () -> JsonValueParser.parse("\"\\u+041\""));
        assertThrows(IllegalArgumentException.class, () -> JsonValueParser.parse("\"\\u-041\""));
        assertEquals("A", JsonValueParser.parse("\"\\u0041\""));
    }
}
