package ai.lmctl.lmdb;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Properties;

/** Secrets enter through the environment or a UTF-8 properties file, never argv. */
public final class Credentials {
    private Credentials() {}

    public static Properties read(String file) throws IOException {
        Properties properties = new Properties();
        if (file != null) {
            try (var reader = Files.newBufferedReader(Path.of(file), StandardCharsets.UTF_8)) {
                properties.load(reader);
            }
        }
        String user = System.getenv("LMDB_USER");
        String password = System.getenv("LMDB_PASSWORD");
        if (user != null) properties.setProperty("user", user);
        if (password != null) properties.setProperty("password", password);
        return properties;
    }

    public static void validateUrl(String url) {
        if (url == null || !url.startsWith("jdbc:"))
            throw new IllegalArgumentException("a JDBC URL is required (--url or LMDB_URL)");
        String lower = url.toLowerCase(java.util.Locale.ROOT);
        if (lower.matches("(?s).*(?:password|passwd|pwd|user|username)\\s*=.*") || url.contains("@"))
            throw new IllegalArgumentException("put JDBC credentials in environment variables or --credentials-file, never the URL");
    }
}
