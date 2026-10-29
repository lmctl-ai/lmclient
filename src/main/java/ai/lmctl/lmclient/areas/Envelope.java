package ai.lmctl.lmclient.areas;

/**
 * One JSON envelope on stdout per run, shared by every protocol area:
 * {"ok":true,"result":...} or {"ok":false,"error":{"code","message"}}.
 * Exit codes: 0 ok, 3 runtime failure, 2 usage. Human text goes to stderr.
 */
public final class Envelope {
    private Envelope() {}

    public static int ok(String resultJson) {
        System.out.println("{\"ok\":true,\"result\":" + resultJson + "}");
        return 0;
    }

    public static int fail(String code, String message) {
        System.out.println("{\"ok\":false,\"error\":{\"code\":\"" + code + "\",\"message\":" + quote(message) + "}}");
        return code.equals("USAGE") ? 2 : 3;
    }

    /** Minimal JSON string quoting for messages and values built by hand. */
    public static String quote(String s) {
        if (s == null) return "null";
        StringBuilder out = new StringBuilder(s.length() + 2).append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                    else out.append(c);
                }
            }
        }
        return out.append('"').toString();
    }
}
