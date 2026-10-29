package ai.lmctl.lmclient.areas;

import java.nio.charset.StandardCharsets;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * cred area — the family credential store (shared SQLite schema with lmconn).
 * PINNED CLI contract (wave 6; owner Astra1; details docs/areas/cred.md):
 *   lmclient cred set SERVICE FIELD (--value V | --env VAR | --stdin)
 *   lmclient cred get SERVICE FIELD [--reveal]
 *   lmclient cred list
 *   lmclient cred delete SERVICE FIELD
 *   lmclient cred path
 * Storage: CredStore.java (already implemented). Envelope per Envelope.java.
 * Never print values except `get --reveal`; list shows names+timestamps only.
 */
public final class CredArea {
    private CredArea() {}
    private static int usage() {
        return Envelope.fail("USAGE", "Usage: cred set SERVICE FIELD (--value V | --env VAR | --stdin), get SERVICE FIELD [--reveal], delete SERVICE FIELD, list, or path");
    }

    public static int run(String[] args) {
        if (args.length == 0 || !Set.of("set", "get", "list", "delete", "path").contains(args[0])) return usage();
        String command = args[0];
        if (command.equals("list") || command.equals("path")) {
            if (args.length != 1) return usage();
        } else {
            if (args.length < 3 || args[1].isEmpty() || args[2].isEmpty() ||
                    args[1].startsWith("--") || args[2].startsWith("--")) return usage();
            if (command.equals("delete") && args.length != 3) return usage();
            if (command.equals("get") && !(args.length == 3 || (args.length == 4 && args[3].equals("--reveal")))) return usage();
            if (command.equals("set") && !(
                    (args.length == 4 && args[3].equals("--stdin")) ||
                    (args.length == 5 && Set.of("--value", "--env").contains(args[3]) && !args[4].startsWith("--")))) return usage();
        }
        try {
            if (command.equals("path")) return Envelope.ok("{\"path\":" + Envelope.quote(CredStore.path()) + "}");
            if (command.equals("list")) {
                String rows = CredStore.list().stream().map(row -> "{\"service\":" + Envelope.quote(row[0]) +
                        ",\"field\":" + Envelope.quote(row[1]) + ",\"updated_at\":" + Envelope.quote(row[2]) + "}")
                        .collect(Collectors.joining(",", "[", "]"));
                return Envelope.ok(rows);
            }
            String service = args[1];
            String field = args[2];
            String identity = "\"service\":" + Envelope.quote(service) + ",\"field\":" + Envelope.quote(field);
            if (command.equals("delete")) return Envelope.ok("{\"deleted\":" + CredStore.delete(service, field) + "}");
            if (command.equals("get")) {
                String value = CredStore.get(service, field);
                boolean reveal = args.length == 4;
                if (reveal && value == null) return Envelope.fail("NOT_FOUND", "Credential not found");
                return Envelope.ok("{" + identity + ",\"set\":" + (value != null) +
                        (reveal ? ",\"value\":" + Envelope.quote(value) : "") + "}");
            }
            String value;
            switch (args[3]) {
                case "--env" -> {
                    value = System.getenv(args[4]);
                    if (args[4].isEmpty() || value == null)
                        return Envelope.fail("USAGE", "The named environment variable must be set");
                }
                case "--stdin" -> {
                    // Read the pipe to EOF directly, including on Windows; no console,
                    // platform charset, line reader, or /dev/stdin dependency. Do not
                    // close System.in: callers can invoke this area in-process.
                    value = new String(System.in.readAllBytes(), StandardCharsets.UTF_8);
                    // Strip exactly one shell line ending, not other credential whitespace.
                    if (value.endsWith("\r\n")) value = value.substring(0, value.length() - 2);
                    else if (value.endsWith("\n")) value = value.substring(0, value.length() - 1);
                }
                default -> {
                    System.err.println("Warning: --value exposes credentials in argv, which is visible to other processes. Prefer --env or --stdin.");
                    value = args[4];
                }
            }
            CredStore.set(service, field, value);
            return Envelope.ok("{" + identity + ",\"stored\":true}");
        } catch (Exception ex) {
            // Never include exception messages: paths, input, or driver errors may contain secrets.
            return Envelope.fail("CREDENTIAL_ERROR", "Credential operation failed");
        }
    }
}
