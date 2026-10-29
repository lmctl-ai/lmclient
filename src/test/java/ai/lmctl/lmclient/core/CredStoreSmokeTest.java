package ai.lmctl.lmclient.core;

import ai.lmctl.lmclient.areas.CredStore;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.Comparator;
import java.util.concurrent.TimeUnit;

/** Dependency-free store checks. A child JVM isolates LMCLIENT_DB without mutating JVM environment internals. */
public final class CredStoreSmokeTest {
    private CredStoreSmokeTest() {}

    public static void main(String[] args) throws Exception {
        if (args.length == 1 && args[0].equals("--worker")) {
            checkStore();
            return;
        }
        Path directory = Files.createTempDirectory("lmclient-cred-smoke-");
        Process child = null;
        try {
            String executable = System.getProperty("os.name").startsWith("Windows") ? "java.exe" : "java";
            ProcessBuilder builder = new ProcessBuilder(
                    Path.of(System.getProperty("java.home"), "bin", executable).toString(),
                    "-cp", System.getProperty("java.class.path"), CredStoreSmokeTest.class.getName(), "--worker");
            builder.environment().put("LMCLIENT_DB", directory.resolve("creds.db").toString());
            child = builder.inheritIO().start();
            require(child.waitFor(60, TimeUnit.SECONDS), "credential store smoke timed out");
            require(child.exitValue() == 0, "credential store smoke worker failed");
        } finally {
            if (child != null && child.isAlive()) {
                child.destroyForcibly();
                child.waitFor();
            }
            // Each CredStore operation closes its connection; deletion also checks Windows handle cleanup.
            try (var paths = Files.walk(directory)) {
                for (Path path : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(path);
            }
        }
        System.out.println("lmclient credential store smoke tests: PASS");
    }

    private static void checkStore() {
        String[][] identifiers = {
                {"quoted\"service", "field"}, {"backslash\\service", "field"},
                {"世界", "field"}, {"service", "line\nfield"},
                {"quoted\"service\\世界", "line\nfield"}
        };
        String value = "dummy-store-secret";
        require(CredStore.list().isEmpty(), "fresh credential store");
        for (String[] pair : identifiers) {
            require(CredStore.get(pair[0], pair[1]) == null, "initially missing");
            CredStore.set(pair[0], pair[1], value);
            require(value.equals(CredStore.get(pair[0], pair[1])), "identifier round trip");
        }
        var rows = CredStore.list();
        require(rows.size() == identifiers.length, "list row count");
        for (String[] pair : identifiers) {
            require(rows.stream().filter(row -> row[0].equals(pair[0]) && row[1].equals(pair[1])).count() == 1,
                    "list preserves identifier");
        }
        for (String[] row : rows) {
            require(row.length == 3, "list contains only names and timestamp");
            Instant.parse(row[2]);
            for (String column : row) require(!column.contains(value), "list redacts value");
        }
        for (String[] pair : identifiers) {
            CredStore.set(pair[0], pair[1], value + "-updated");
            require((value + "-updated").equals(CredStore.get(pair[0], pair[1])), "update round trip");
            require(CredStore.delete(pair[0], pair[1]), "delete present");
            require(CredStore.get(pair[0], pair[1]) == null, "deleted value missing");
            require(!CredStore.delete(pair[0], pair[1]), "delete absent");
        }
        require(CredStore.list().isEmpty(), "store empty after deletion");
    }

    private static void require(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
}
