package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.Drivers;
import ai.lmctl.lmclient.core.Env;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.sql.Connection;
import java.sql.DriverManager;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * Family-shared credential store: the same SQLite schema as lmconn
 * (creds(service, field, value, updated_at), primary key service+field), so
 * lmconn and lmclient read and write one store. Secrets never print here;
 * callers decide what reaches the envelope.
 *
 * Path resolution: LMCLIENT_DB (LMDB_DB legacy alias via Env) > LMCONN_DB >
 * ~/.lmconn/creds.db, falling back to a legacy ~/.lmconnectors/creds.db when
 * only that exists.
 */
public final class CredStore {
    private CredStore() {}

    public static String path() {
        String env = Env.get("LMCLIENT_DB");
        if (env != null) return env;
        env = System.getenv("LMCONN_DB");
        if (env != null) return env;
        Path home = Path.of(System.getProperty("user.home"));
        Path current = home.resolve(".lmconn/creds.db");
        Path legacy = home.resolve(".lmconnectors/creds.db");
        if (!Files.exists(current) && Files.exists(legacy)) return legacy.toString();
        return current.toString();
    }

    private static Connection open() throws Exception {
        Drivers.register(); // idempotent; brings up the bundled sqlite driver
        Path file = Path.of(path());
        Files.createDirectories(file.getParent());
        Connection conn = DriverManager.getConnection("jdbc:sqlite:" + file);
        try (var st = conn.createStatement()) {
            st.execute("CREATE TABLE IF NOT EXISTS creds (service TEXT NOT NULL, field TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (service, field))");
        }
        try {
            Files.setPosixFilePermissions(file, PosixFilePermissions.fromString("rw-------"));
        } catch (UnsupportedOperationException | SecurityException ignored) { /* Windows: ACLs keep it user-private */ }
        return conn;
    }

    public static String get(String service, String field) {
        try (Connection conn = open();
             var ps = conn.prepareStatement("SELECT value FROM creds WHERE service = ? AND field = ?")) {
            ps.setString(1, service);
            ps.setString(2, field);
            var rs = ps.executeQuery();
            return rs.next() ? rs.getString(1) : null;
        } catch (Exception e) {
            throw new IllegalStateException("credential store unavailable");
        }
    }

    public static void set(String service, String field, String value) {
        try (Connection conn = open();
             var ps = conn.prepareStatement("INSERT INTO creds (service, field, value, updated_at) VALUES (?, ?, ?, ?) " +
                 "ON CONFLICT (service, field) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at")) {
            ps.setString(1, service);
            ps.setString(2, field);
            ps.setString(3, value);
            ps.setString(4, Instant.now().toString());
            ps.executeUpdate();
        } catch (Exception e) {
            throw new IllegalStateException("credential store unavailable");
        }
    }

    public static boolean delete(String service, String field) {
        try (Connection conn = open();
             var ps = conn.prepareStatement("DELETE FROM creds WHERE service = ? AND field = ?")) {
            ps.setString(1, service);
            ps.setString(2, field);
            return ps.executeUpdate() > 0;
        } catch (Exception e) {
            throw new IllegalStateException("credential store unavailable");
        }
    }

    /** Names and timestamps only, never values: rows of [service, field, updated_at]. */
    public static List<String[]> list() {
        try (Connection conn = open();
             var st = conn.createStatement()) {
            var rs = st.executeQuery("SELECT service, field, updated_at FROM creds ORDER BY service, field");
            List<String[]> rows = new ArrayList<>();
            while (rs.next()) rows.add(new String[] { rs.getString(1), rs.getString(2), rs.getString(3) });
            return rows;
        } catch (Exception e) {
            throw new IllegalStateException("credential store unavailable");
        }
    }
}
