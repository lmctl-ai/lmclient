package ai.lmctl.lmdb;

import java.sql.Connection;
import java.sql.Driver;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Registration and no-server smoke tests for the drivers bundled in lmdb. */
public final class Drivers {
    private record Bundled(String name, String className, String testUrl, boolean embedded) {}

    private static final List<Bundled> BUNDLED = List.of(
            new Bundled("postgresql", "org.postgresql.Driver", "jdbc:postgresql://127.0.0.1:1/lmdb", false),
            new Bundled("sqlite", "org.sqlite.JDBC", "jdbc:sqlite::memory:", true),
            new Bundled("h2", "org.h2.Driver", "jdbc:h2:mem:lmdb_driver_test;DB_CLOSE_DELAY=-1", true),
            new Bundled("duckdb", "org.duckdb.DuckDBDriver", "jdbc:duckdb:", true),
            new Bundled("sqlserver", "com.microsoft.sqlserver.jdbc.SQLServerDriver", "jdbc:sqlserver://127.0.0.1:1;databaseName=master", false));

    private Drivers() {}

    /** Explicitly registers every bundled driver without printing connection data. */
    public static synchronized void register() throws SQLException {
        for (Bundled bundled : BUNDLED) {
            try {
                Driver driver = switch (bundled.name()) {
                    case "postgresql" -> new org.postgresql.Driver();
                    case "sqlite" -> new org.sqlite.JDBC();
                    case "h2" -> new org.h2.Driver();
                    case "duckdb" -> new org.duckdb.DuckDBDriver();
                    case "sqlserver" -> new com.microsoft.sqlserver.jdbc.SQLServerDriver();
                    default -> throw new IllegalStateException("unknown bundled driver");
                };
                if (!isRegistered(bundled.className())) {
                    DriverManager.registerDriver(driver);
                }
            } catch (RuntimeException e) {
                throw new SQLException("bundled JDBC driver unavailable: " + bundled.name(), e);
            }
        }
    }

    private static boolean isRegistered(String className) {
        var drivers = DriverManager.getDrivers();
        while (drivers.hasMoreElements()) {
            if (drivers.nextElement().getClass().getName().equals(className)) return true;
        }
        return false;
    }

    /**
     * Runs deterministic embedded queries and URL acceptance checks. Values are deliberately
     * generic so this result can be shown to a caller without exposing credentials.
     */
    public static Map<String, String> selfTest() throws SQLException {
        register();
        Map<String, String> result = new LinkedHashMap<>();
        for (Bundled bundled : BUNDLED) {
            try {
                Driver driver = find(bundled.className());
                if (bundled.embedded()) {
                    try (Connection connection = DriverManager.getConnection(bundled.testUrl());
                         Statement statement = connection.createStatement();
                         ResultSet rows = statement.executeQuery("SELECT 1")) {
                        if (!rows.next() || rows.getInt(1) != 1) throw new SQLException("unexpected result");
                    }
                } else if (!driver.acceptsURL(bundled.testUrl())) {
                    throw new SQLException("driver rejected its JDBC URL");
                }
                result.put(bundled.name(), "ok");
            } catch (SQLException | RuntimeException e) {
                result.put(bundled.name(), "error");
            }
        }
        return result;
    }

    private static Driver find(String className) throws SQLException {
        var drivers = DriverManager.getDrivers();
        while (drivers.hasMoreElements()) {
            Driver candidate = drivers.nextElement();
            if (candidate.getClass().getName().equals(className)) return candidate;
        }
        throw new SQLException("driver not registered");
    }

    public static List<String> names() {
        return BUNDLED.stream().map(Bundled::name).toList();
    }
}
