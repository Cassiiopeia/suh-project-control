package kr.suhsaechan.controltower;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 의존성 없는 최소 JSON 해석: 응답 본문 > Map·List·String·BigDecimal·Boolean·null
 * 형식이 틀리면 IllegalArgumentException
 */
final class JsonValueParser {

    private final String text;
    private int position;

    private JsonValueParser(String text) {
        this.text = text;
    }

    static Object parse(String text) {
        JsonValueParser parser = new JsonValueParser(text);
        Object value = parser.readValue();
        parser.skipWhitespace();
        if (parser.position != text.length()) {
            throw parser.error("trailing characters");
        }
        return value;
    }

    private Object readValue() {
        skipWhitespace();
        if (position >= text.length()) {
            throw error("unexpected end");
        }
        char current = text.charAt(position);
        return switch (current) {
            case '{' -> readObject();
            case '[' -> readArray();
            case '"' -> readString();
            case 't' -> readLiteral("true", Boolean.TRUE);
            case 'f' -> readLiteral("false", Boolean.FALSE);
            case 'n' -> readLiteral("null", null);
            default -> readNumber();
        };
    }

    private Map<String, Object> readObject() {
        Map<String, Object> object = new LinkedHashMap<>();
        position++;
        skipWhitespace();
        if (consumeIf('}')) {
            return object;
        }
        do {
            skipWhitespace();
            if (position >= text.length() || text.charAt(position) != '"') {
                throw error("expected object key");
            }
            String key = readString();
            skipWhitespace();
            expect(':');
            object.put(key, readValue());
            skipWhitespace();
        } while (consumeIf(','));
        expect('}');
        return object;
    }

    private List<Object> readArray() {
        List<Object> array = new ArrayList<>();
        position++;
        skipWhitespace();
        if (consumeIf(']')) {
            return array;
        }
        do {
            array.add(readValue());
            skipWhitespace();
        } while (consumeIf(','));
        expect(']');
        return array;
    }

    private String readString() {
        StringBuilder output = new StringBuilder();
        position++;
        while (position < text.length()) {
            char current = text.charAt(position++);
            if (current == '"') {
                return output.toString();
            }
            if (current != '\\') {
                output.append(current);
                continue;
            }
            if (position >= text.length()) {
                break;
            }
            char escaped = text.charAt(position++);
            switch (escaped) {
                case '"', '\\', '/' -> output.append(escaped);
                case 'n' -> output.append('\n');
                case 'r' -> output.append('\r');
                case 't' -> output.append('\t');
                case 'b' -> output.append('\b');
                case 'f' -> output.append('\f');
                case 'u' -> output.append(readUnicodeEscape());
                default -> throw error("invalid escape");
            }
        }
        throw error("unterminated string");
    }

    private char readUnicodeEscape() {
        if (position + 4 > text.length()) {
            throw error("short unicode escape");
        }
        try {
            char decoded = (char) Integer.parseInt(text.substring(position, position + 4), 16);
            position += 4;
            return decoded;
        } catch (NumberFormatException invalidHex) {
            throw error("invalid unicode escape");
        }
    }

    private Object readLiteral(String literal, Object value) {
        if (!text.startsWith(literal, position)) {
            throw error("invalid literal");
        }
        position += literal.length();
        return value;
    }

    private BigDecimal readNumber() {
        int start = position;
        while (position < text.length() && "+-0123456789.eE".indexOf(text.charAt(position)) >= 0) {
            position++;
        }
        try {
            return new BigDecimal(text.substring(start, position));
        } catch (NumberFormatException invalidNumber) {
            throw error("invalid value");
        }
    }

    private void skipWhitespace() {
        while (position < text.length() && " \t\n\r".indexOf(text.charAt(position)) >= 0) {
            position++;
        }
    }

    private boolean consumeIf(char expected) {
        if (position < text.length() && text.charAt(position) == expected) {
            position++;
            return true;
        }
        return false;
    }

    private void expect(char expected) {
        if (!consumeIf(expected)) {
            throw error("expected '" + expected + "'");
        }
    }

    private IllegalArgumentException error(String reason) {
        return new IllegalArgumentException("invalid json at " + position + " : " + reason);
    }
}
