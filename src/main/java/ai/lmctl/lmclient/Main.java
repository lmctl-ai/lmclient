package ai.lmctl.lmclient;

import ai.lmctl.lmclient.core.Env;
import ai.lmctl.lmclient.core.Database;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;

/** Stateless JDBC command line. Database exceptions never echo queries or credentials. */
public final class Main {
    public static final String VERSION = "0.2.0";
    private Main() {}

    public static void main(String[] args) {
        System.setOut(new java.io.PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new java.io.PrintStream(System.err, true, StandardCharsets.UTF_8));
        int code;
        try { RuntimeBudget.configure(memoryBudget(),args); code = run(args); }
        catch (ai.lmctl.lmclient.core.DatabaseException e) { System.err.println("lmclient: " + e.getMessage()); code = 3; }
        catch (IllegalArgumentException e) { System.err.println("lmclient: " + e.getMessage()); code = 2; }
        catch (Exception e) {
            System.err.println("lmclient: database or file operation failed (" + e.getClass().getSimpleName() + ")");
            code = 3;
        }
        catch (OutOfMemoryError e) {
            System.err.println("lmclient: LMCLIENT_MAX_MEMORY_MB memory budget exceeded");
            if (java.util.Arrays.asList(args).contains("--lmcode"))
                System.out.println("{\"ok\":false,\"phase\":\"run\",\"code\":\"RUN_ERROR\",\"message\":\"LMCLIENT_MAX_MEMORY_MB memory budget exceeded\"}");
            code = 3;
        }
        catch (LinkageError e) { System.err.println("lmclient: bundled native driver could not load (" + e.getClass().getSimpleName() + ")"); code = 3; }
        if (code != 0) System.exit(code);
    }

    public static long memoryBudget() {
        String raw = Env.get("LMCLIENT_MAX_MEMORY_MB");
        if (raw == null) return 4096L * 1024 * 1024;
        try {
            if (!raw.matches("[1-9][0-9]*")) throw new NumberFormatException();
            long megabytes = Long.parseLong(raw);
            return Math.multiplyExact(megabytes, 1024L * 1024);
        } catch (ArithmeticException | NumberFormatException e) {
            throw new IllegalArgumentException("LMCLIENT_MAX_MEMORY_MB must be a positive whole number of MiB");
        }
    }

    static int run(String[] args) throws Exception {
        memoryBudget();
        if (args.length == 0 || args[0].equals("--help")) { usage(); return args.length == 0 ? 2 : 0; }
        switch (args[0]) {
            case "--version": System.out.println("lmclient " + VERSION); return 0;
            case "--lmcode-schema": System.out.print(HostApi.schema()); return 0;
            case "--lmcode-signatures": System.out.print(HostApi.signatures()); return 0;
            case "--drivers": Drivers.names().forEach(System.out::println); return 0;
            case "--notices":
                try (var stream = Main.class.getResourceAsStream("/THIRD_PARTY_NOTICES")) {
                    if (stream == null) throw new IllegalStateException("missing embedded notices");
                    System.out.write(stream.readAllBytes());
                } return 0;
            case "--driver-test":
                var results = Drivers.selfTest();
                results.forEach((name, result) -> System.out.println(name + ": " + result));
                return results.values().stream().allMatch("ok"::equals) ? 0 : 3;
            case "--lmcode":
                boolean dryRun = false;
                String bytecode = null;
                for (int i = 1; i < args.length; i++) {
                    if (args[i].equals("--dry-run")) dryRun = true;
                    else if (args[i].startsWith("--") || bytecode != null) throw new IllegalArgumentException("usage: --lmcode BYTECODE [--dry-run]");
                    else bytecode = args[i];
                }
                if (bytecode == null) throw new IllegalArgumentException("--lmcode requires a bytecode file");
                Drivers.register();
                try (var host = new DslHost()) { return host.run(Path.of(bytecode),dryRun); }
            default: break;
        }
        var area = ai.lmctl.lmclient.areas.Areas.lookup(args[0]);
        if (area != null) return area.run(java.util.Arrays.copyOfRange(args, 1, args.length));
        Map<String, String> options = new LinkedHashMap<>();
        for (int i = 0; i < args.length; i++) {
            if (!java.util.Set.of("--url", "--sql", "--file", "--format", "--output", "--metadata", "--table", "--credentials-file", "--max-rows", "--driver-jar", "--driver-class", "--explain", "--diff-url").contains(args[i]))
                throw new IllegalArgumentException("unknown option; run lmclient --help");
            if (i + 1 == args.length) throw new IllegalArgumentException("option requires a value");
            if (options.put(args[i], args[++i]) != null) throw new IllegalArgumentException("duplicate option");
        }
        String url = options.getOrDefault("--url", Env.get("LMCLIENT_URL"));
        Credentials.validateUrl(url);
        long actions = java.util.List.of("--sql", "--file", "--metadata", "--explain", "--diff-url").stream().filter(options::containsKey).count();
        if (actions != 1) throw new IllegalArgumentException("choose one of --sql, --file, --metadata, --explain or --diff-url");
        Drivers.register();
        if (options.containsKey("--driver-jar"))
            loadExternalDriver(options.get("--driver-jar"), options.get("--driver-class"));
        String format = options.getOrDefault("--format", "table");
        if (!java.util.Set.of("table", "csv", "json").contains(format))
            throw new IllegalArgumentException("format must be table, csv or json");
        int maxRows;
        try { maxRows = Integer.parseInt(options.getOrDefault("--max-rows", "10000")); }
        catch (NumberFormatException e) { throw new IllegalArgumentException("max-rows must be positive"); }
        if (maxRows <= 0 || maxRows > 1_000_000) throw new IllegalArgumentException("max-rows must be between 1 and 1000000");
        var properties = Credentials.read(options.getOrDefault("--credentials-file", Env.get("LMCLIENT_CREDENTIALS_FILE")));
        properties.setProperty("lmclient.maxRows", Integer.toString(maxRows));
        try (var database = Database.connect(url, properties)) {
            String sql = options.get("--sql");
            if (options.containsKey("--file")) {
                if (sql != null) throw new IllegalArgumentException("choose --sql or --file");
                Path file = Path.of(options.get("--file"));
                if (Files.size(file) > memoryBudget() / 4) throw new IllegalArgumentException("SQL file exceeds LMCLIENT_MAX_MEMORY_MB budget");
                sql = Files.readString(file, StandardCharsets.UTF_8);
            }
            String output = execute(database, options, sql, maxRows, format);
            if (options.containsKey("--output")) Files.writeString(Path.of(options.get("--output")), output, StandardCharsets.UTF_8);
            else System.out.print(output);
        }
        return 0;
    }

    private static String execute(Database database, Map<String,String> options, String sql, int maxRows, String format) throws Exception {
        Database.QueryResult result;
        if (options.containsKey("--metadata")) {
            String table = options.get("--table");
            result = switch(options.get("--metadata")) {
                case "schemas" -> database.schemas();
                case "tables" -> database.tables();
                case "views" -> database.views();
                case "columns" -> database.columns(null, table == null ? "%" : table);
                case "keys" -> database.keys(null, requiredTable(table));
                case "foreign_keys" -> database.foreignKeys(null, requiredTable(table));
                case "indexes" -> database.indexes(null, requiredTable(table));
                default -> throw new IllegalArgumentException("unknown metadata kind");
            };
        } else if (options.containsKey("--explain")) result = database.explain(options.get("--explain"));
        else if (options.containsKey("--diff-url")) {
            String otherUrl = options.get("--diff-url");
            Credentials.validateUrl(otherUrl);
            try (var other = Database.connect(otherUrl, Credentials.read(options.get("--credentials-file")))) {
                result = Database.diff(database.snapshot(),other.snapshot());
            }
        }
        else {
            if (sql == null) throw new IllegalArgumentException("provide --sql, --file or --metadata");
            var statements = ai.lmctl.lmclient.core.SqlScript.split(sql);
            if (statements.isEmpty()) throw new IllegalArgumentException("SQL must not be empty");
            result = null;
            for (String statement : statements) result = database.query(statement, maxRows);
        }
        return switch (format) { case "csv" -> Database.csv(result); case "json" -> Database.json(result); default -> Database.table(result); };
    }

    private static String requiredTable(String table) {
        if (table == null) throw new IllegalArgumentException("this metadata kind requires --table NAME");
        return table;
    }

    private static void loadExternalDriver(String jar, String className) throws Exception {
        if (System.getProperty("org.graalvm.nativeimage.imagecode") != null)
            throw new IllegalArgumentException("optional JDBC jars require the JVM distribution or a custom native build");
        if (className == null) throw new IllegalArgumentException("--driver-jar requires --driver-class");
        var loader = new java.net.URLClassLoader(new java.net.URL[]{Path.of(jar).toUri().toURL()}, Main.class.getClassLoader());
        var driver = (java.sql.Driver) Class.forName(className, true, loader).getConstructor().newInstance();
        java.sql.DriverManager.registerDriver(new DriverDelegate(driver));
    }

    private record DriverDelegate(java.sql.Driver driver) implements java.sql.Driver {
        public java.sql.Connection connect(String url, java.util.Properties properties) throws java.sql.SQLException { return driver.connect(url, properties); }
        public boolean acceptsURL(String url) throws java.sql.SQLException { return driver.acceptsURL(url); }
        public java.sql.DriverPropertyInfo[] getPropertyInfo(String url,java.util.Properties properties) throws java.sql.SQLException { return driver.getPropertyInfo(url, properties); }
        public int getMajorVersion() { return driver.getMajorVersion(); }
        public int getMinorVersion() { return driver.getMinorVersion(); }
        public boolean jdbcCompliant() { return driver.jdbcCompliant(); }
        public java.util.logging.Logger getParentLogger() throws java.sql.SQLFeatureNotSupportedException { return driver.getParentLogger(); }
    }

    private static void usage() {
        System.out.println("""
            lmclient: portable scriptable protocol client (JDBC databases plus redis/mail/queue/mqtt/mongo areas)
            lmclient --url JDBC_URL --sql SQL [--format table|csv|json] [--output FILE]
            lmclient --url JDBC_URL --file SQL_FILE [--max-rows N]
            lmclient --url JDBC_URL --metadata schemas|tables|views|columns|keys|foreign_keys|indexes [--table NAME]
            lmclient --url JDBC_URL --explain SQL
            lmclient --url JDBC_URL --diff-url OTHER_JDBC_URL
            lmclient --lmcode BYTECODE [--dry-run] | --lmcode-schema | --lmcode-signatures
            lmclient --drivers | --driver-test | --version | --notices
            lmclient redis|mail|queue|mqtt|mongo ...   (protocol areas; see docs/areas/)
            Credentials: LMCLIENT_USER, LMCLIENT_PASSWORD, or --credentials-file UTF8_PROPERTIES.
            URL fallback: LMCLIENT_URL. Optional drivers: --driver-jar JAR --driver-class CLASS (JVM only).
            LMCLIENT_MAX_MEMORY_MB: positive whole MiB; default 4096. Results default to 10000 rows.
            Linux binaries require glibc 2.35 or newer.
            """);
    }
}
