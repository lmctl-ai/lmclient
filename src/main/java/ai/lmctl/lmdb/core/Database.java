package ai.lmctl.lmdb.core;

import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.Blob;
import java.sql.Clob;
import java.sql.DatabaseMetaData;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Properties;
import java.io.InputStream;
import java.io.Reader;

/** Small, bounded JDBC facade used by the command line client and lmcode host. */
public final class Database implements AutoCloseable {
    public static final int DEFAULT_MAX_ROWS = 10_000;
    public static final int DEFAULT_MAX_CELL_BYTES = 4 * 1024 * 1024;
    public static final int DEFAULT_QUERY_TIMEOUT_SECONDS = 30;
    public record QueryResult(List<String> columns, List<List<Object>> rows, long updateCount) {
        public QueryResult {
            columns = List.copyOf(columns);
            rows = rows.stream().map(row -> Collections.unmodifiableList(new ArrayList<>(row))).toList();
        }
        public boolean isQuery() { return !columns.isEmpty(); }
    }
    public record Column(String schema, String table, String name, int jdbcType,
                         String typeName, boolean nullable, int ordinal) {}
    public record Key(String schema, String table, String name, String column,
                      short keySequence, boolean primary) {}
    public record Index(String schema, String table, String name, String column,
                        boolean unique, short ordinal) {}
    public record ForeignKey(String primarySchema, String primaryTable, String primaryColumn,
                             String foreignSchema, String foreignTable, String foreignColumn,
                             String name, short keySequence) {}
    public record SchemaSnapshot(Map<String, List<Column>> columns,
                                 List<Key> keys, List<Index> indexes, List<ForeignKey> foreignKeys) {
        public SchemaSnapshot(Map<String, List<Column>> columns, List<Key> keys, List<Index> indexes) {
            this(columns, keys, indexes, List.of());
        }
        public SchemaSnapshot {
            columns = Collections.unmodifiableMap(new LinkedHashMap<>(columns));
            keys = List.copyOf(keys); indexes = List.copyOf(indexes); foreignKeys = List.copyOf(foreignKeys);
        }
    }

    private final Connection connection;
    private final int maxRows;
    private final int maxCellBytes;
    private boolean closed;

    private Database(Connection connection, int maxRows, int maxCellBytes) {
        this.connection = connection;
        this.maxRows = maxRows;
        this.maxCellBytes = maxCellBytes;
    }

    /** Connect without retaining or printing credentials. Properties are copied. */
    public static Database connect(String url, Properties properties) {
        Objects.requireNonNull(url, "url");
        Properties p = new Properties();
        if (properties != null) p.putAll(properties);
        int rows = positiveInt(p, "lmdb.maxRows", DEFAULT_MAX_ROWS);
        int bytes = positiveInt(p, "lmdb.maxCellBytes", DEFAULT_MAX_CELL_BYTES);
        p.remove("lmdb.maxRows"); p.remove("lmdb.maxCellBytes");
        try {
            DriverManager.setLoginTimeout(DEFAULT_QUERY_TIMEOUT_SECONDS);
            return new Database(DriverManager.getConnection(url, p), rows, bytes);
        } catch (SQLException e) {
            throw DatabaseException.from(e);
        }
    }

    private static int positiveInt(Properties p, String key, int fallback) {
        String value = p.getProperty(key);
        if (value == null || value.isBlank()) return fallback;
        try {
            int n = Integer.parseInt(value);
            if (n <= 0) throw new IllegalArgumentException(key + " must be positive");
            return n;
        } catch (NumberFormatException e) { throw new IllegalArgumentException(key + " must be an integer"); }
    }

    public QueryResult query(String sql) { return query(sql, maxRows); }
    public QueryResult query(String sql, int rowLimit) {
        ensureOpen();
        if (sql == null || sql.isBlank()) throw new IllegalArgumentException("SQL must not be empty");
        if (rowLimit <= 0) throw new IllegalArgumentException("maxRows must be positive");
        try (Statement statement = connection.createStatement()) {
            int effectiveLimit = Math.min(rowLimit, maxRows);
            statement.setQueryTimeout(DEFAULT_QUERY_TIMEOUT_SECONDS);
            statement.setMaxRows(effectiveLimit == Integer.MAX_VALUE ? effectiveLimit : effectiveLimit + 1);
            boolean result = statement.execute(sql);
            if (result) return read(statement.getResultSet(), effectiveLimit);
            return new QueryResult(List.of(), List.of(), statement.getUpdateCount());
        } catch (SQLException e) { throw DatabaseException.from(e); }
    }

    public QueryResult query(String sql, List<?> parameters, int rowLimit) {
        ensureOpen();
        if (sql == null || sql.isBlank()) throw new IllegalArgumentException("SQL must not be empty");
        if (rowLimit <= 0) throw new IllegalArgumentException("maxRows must be positive");
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            bind(statement, parameters);
            int effectiveLimit = Math.min(rowLimit, maxRows);
            statement.setQueryTimeout(DEFAULT_QUERY_TIMEOUT_SECONDS);
            statement.setMaxRows(effectiveLimit == Integer.MAX_VALUE ? effectiveLimit : effectiveLimit + 1);
            boolean result = statement.execute();
            return result ? read(statement.getResultSet(), effectiveLimit)
                    : new QueryResult(List.of(), List.of(), statement.getUpdateCount());
        } catch (SQLException e) { throw DatabaseException.from(e); }
    }

    private void bind(PreparedStatement statement, List<?> values) throws SQLException {
        if (values == null) return;
        for (int i = 0; i < values.size(); i++) statement.setObject(i + 1, values.get(i));
    }

    private QueryResult read(ResultSet result, int rowLimit) throws SQLException {
        try (result) {
            ResultSetMetaData metadata = result.getMetaData();
            List<String> columns = new ArrayList<>(metadata.getColumnCount());
            for (int i = 1; i <= metadata.getColumnCount(); i++) columns.add(metadata.getColumnLabel(i));
            List<List<Object>> rows = new ArrayList<>();
            ReadBudget budget = new ReadBudget(memoryBudgetBytes());
            budget.add(64L + columns.stream().mapToLong(Database::estimateBytes).sum());
            while (result.next()) {
                List<Object> row = new ArrayList<>(columns.size());
                if (rows.size() >= rowLimit) throw new DatabaseException("result exceeds max row limit of " + rowLimit);
                budget.add(64L + 16L * columns.size());
                for (int i = 1; i <= columns.size(); i++) row.add(readValue(result, i, budget));
                rows.add(row);
            }
            return new QueryResult(columns, rows, -1);
        }
    }

    private Object safeValue(Object value) {
        if (value instanceof byte[] bytes && bytes.length > maxCellBytes)
            throw new DatabaseException("result cell exceeds configured limit");
        if (value instanceof String s && s.getBytes(StandardCharsets.UTF_8).length > maxCellBytes)
            throw new DatabaseException("result cell exceeds configured limit");
        return value;
    }

    private Object readValue(ResultSet result, int column, ReadBudget budget) throws SQLException {
        Object value = result.getObject(column);
        if (value instanceof Clob clob) {
            long length = clob.length();
            if (length > maxCellBytes) throw new DatabaseException("result cell exceeds configured limit");
            value = clob.getSubString(1, (int) length);
        } else if (value instanceof Blob blob) {
            long length = blob.length();
            if (length > maxCellBytes) throw new DatabaseException("result cell exceeds configured limit");
            value = blob.getBytes(1, (int) length);
        } else if (value instanceof Reader reader) {
            value = readText(reader);
        } else if (value instanceof InputStream stream) {
            value = readBytes(stream);
        }
        Object safe = safeValue(value);
        budget.add(estimateBytes(safe));
        return safe;
    }

    private String readText(Reader reader) throws SQLException {
        try (reader) {
            char[] buffer = new char[Math.min(maxCellBytes, 8192)];
            StringBuilder text = new StringBuilder(); int count;
            while ((count = reader.read(buffer)) >= 0) {
                text.append(buffer, 0, count);
                if (text.length() > maxCellBytes) throw new DatabaseException("result cell exceeds configured limit");
            }
            return text.toString();
        } catch (IOException e) { throw new SQLException("could not read result text", e); }
    }
    private byte[] readBytes(InputStream stream) throws SQLException {
        try (stream) {
            byte[] buffer = new byte[Math.min(maxCellBytes, 8192)];
            java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream(); int count;
            while ((count = stream.read(buffer)) >= 0) {
                if (out.size() + count > maxCellBytes) throw new DatabaseException("result cell exceeds configured limit");
                out.write(buffer, 0, count);
            }
            return out.toByteArray();
        } catch (IOException e) { throw new SQLException("could not read result bytes", e); }
    }
    private static long estimateBytes(Object value) {
        if (value == null) return 4;
        if (value instanceof byte[] b) return b.length;
        if (value instanceof String s) return (long) s.length() * 2;
        return 64;
    }
    private static long memoryBudgetBytes() {
        String raw = System.getenv("LMDB_MAX_MEMORY_MB");
        if (raw == null || raw.isBlank()) return 4096L * 1024 * 1024;
        try {
            if (!raw.matches("[1-9][0-9]*")) throw new NumberFormatException();
            return Math.multiplyExact(Long.parseLong(raw), 1024L * 1024);
        } catch (NumberFormatException | ArithmeticException e) {
            throw new IllegalArgumentException("LMDB_MAX_MEMORY_MB must be a positive whole number of MiB");
        }
    }
    private static final class ReadBudget {
        private final long limit; private long used;
        ReadBudget(long limit) { this.limit = limit; }
        void add(long bytes) { if (bytes > limit - used) throw new DatabaseException("LMDB_MAX_MEMORY_MB memory budget exceeded"); used += Math.max(0, bytes); }
    }

    public QueryResult schemas() { return metadata("getSchemas", new String[]{"TABLE_SCHEM"}); }
    public QueryResult tables() { return metadata("getTables", new String[]{"TABLE_SCHEM", "TABLE_NAME", "TABLE_TYPE"}); }
    public QueryResult views() { return metadata("getViews", new String[]{"TABLE_SCHEM", "TABLE_NAME", "TABLE_TYPE"}); }
    public QueryResult columns(String schema, String table) {
        return metadata("getColumns", new String[]{"TABLE_SCHEM", "TABLE_NAME", "COLUMN_NAME", "DATA_TYPE", "TYPE_NAME", "NULLABLE", "ORDINAL_POSITION"}, schema, table);
    }
    public QueryResult keys(String schema, String table) {
        return metadata("getPrimaryKeys", new String[]{"TABLE_SCHEM", "TABLE_NAME", "PK_NAME", "COLUMN_NAME", "KEY_SEQ"}, schema, table);
    }
    public QueryResult indexes(String schema, String table) {
        return metadata("getIndexInfo", new String[]{"TABLE_SCHEM", "TABLE_NAME", "INDEX_NAME", "COLUMN_NAME", "NON_UNIQUE", "ORDINAL_POSITION"}, schema, table);
    }
    public QueryResult foreignKeys(String schema, String table) {
        return metadata("getImportedKeys", new String[]{"PKTABLE_SCHEM", "PKTABLE_NAME", "PKCOLUMN_NAME", "FKTABLE_SCHEM", "FKTABLE_NAME", "FKCOLUMN_NAME", "FK_NAME", "KEY_SEQ"}, schema, table);
    }

    private QueryResult metadata(String operation, String[] wanted, String... args) {
        ensureOpen();
        try {
            DatabaseMetaData md = connection.getMetaData();
            ResultSet rs;
            if (operation.equals("getSchemas")) rs = md.getSchemas();
            else if (operation.equals("getViews")) rs = md.getTables(null, null, "%", new String[]{"VIEW"});
            else if (operation.equals("getTables")) rs = md.getTables(null, args.length > 0 ? args[0] : null, "%", args.length > 1 ? new String[]{args[1]} : new String[]{"TABLE", "VIEW"});
            else if (operation.equals("getColumns")) rs = md.getColumns(null, args[0], args[1], "%");
            else if (operation.equals("getPrimaryKeys")) rs = md.getPrimaryKeys(null, args[0], args[1]);
            else if (operation.equals("getImportedKeys")) rs = md.getImportedKeys(null, args[0], args[1]);
            else rs = md.getIndexInfo(null, args[0], args[1], false, false);
            try (rs) {
                List<List<Object>> rows = new ArrayList<>();
                ReadBudget budget = new ReadBudget(memoryBudgetBytes());
                while (rs.next()) {
                    if (rows.size() >= maxRows) throw new DatabaseException("metadata exceeds max row limit of " + maxRows);
                    budget.add(64L + 16L * wanted.length);
                    List<Object> row = new ArrayList<>();
                    for (String name : wanted) {
                        Object value;
                        try { value = rs.getObject(name); } catch (SQLException ignored) { value = null; }
                        Object safe = safeValue(value); budget.add(estimateBytes(safe)); row.add(safe);
                    }
                    rows.add(row);
                }
                return new QueryResult(List.of(wanted), rows, -1);
            }
        } catch (SQLException e) { throw DatabaseException.from(e); }
    }

    public QueryResult explain(String sql) {
        Objects.requireNonNull(sql, "sql");
        ensureOpen();
        try {
            String product = connection.getMetaData().getDatabaseProductName().toLowerCase(Locale.ROOT);
            if (product.contains("sql server") || product.contains("microsoft sql")) return explainSqlServer(sql);
            return query("EXPLAIN " + sql);
        } catch (SQLException e) { throw DatabaseException.from(e); }
    }

    private QueryResult explainSqlServer(String sql) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.setQueryTimeout(DEFAULT_QUERY_TIMEOUT_SECONDS);
            statement.execute("SET SHOWPLAN_XML ON");
            try (ResultSet result = statement.executeQuery(sql)) { return read(result, maxRows); }
            finally { try { statement.execute("SET SHOWPLAN_XML OFF"); } catch (SQLException ignored) { /* preserve plan error */ } }
        }
    }

    public List<QueryResult> executeScript(String script) {
        List<QueryResult> results = new ArrayList<>();
        for (String statement : SqlScript.split(script)) results.add(query(statement));
        return List.copyOf(results);
    }

    public SchemaSnapshot snapshot() {
        Map<String, List<Column>> cols = new LinkedHashMap<>();
        List<List<Object>> tableRows = tables().rows();
        for (List<Object> table : tableRows) {
            if (!isTableType(text(table, 2))) continue;
            String schema = nullableText(table, 0), name = nullableText(table, 1);
            if (isSystemSchema(schema)) continue;
            for (List<Object> row : columns(schema, name).rows()) {
            String key = text(row, 0) + "." + text(row, 1);
            cols.computeIfAbsent(key, ignored -> new ArrayList<>()).add(new Column(text(row, 0), text(row, 1), text(row, 2), number(row, 3), text(row, 4), number(row, 5) != 0, number(row, 6)));
            }
        }
        List<Key> keys = new ArrayList<>();
        List<Index> indexes = new ArrayList<>();
        List<ForeignKey> foreignKeys = new ArrayList<>();
        for (List<Object> table : tableRows) {
            if (!isTableType(text(table, 2))) continue;
            String schema = nullableText(table, 0), name = nullableText(table, 1);
            if (isSystemSchema(schema)) continue;
            for (List<Object> row : keys(schema, name).rows()) keys.add(new Key(text(row,0), text(row,1), text(row,2), text(row,3), (short)number(row,4), true));
            for (List<Object> row : indexes(schema, name).rows()) indexes.add(new Index(text(row,0), text(row,1), text(row,2), text(row,3), !bool(row,4), (short)number(row,5)));
            for (List<Object> row : foreignKeys(schema, name).rows()) foreignKeys.add(new ForeignKey(text(row,0), text(row,1), text(row,2), text(row,3), text(row,4), text(row,5), text(row,6), (short)number(row,7)));
        }
        return new SchemaSnapshot(cols, keys, indexes, foreignKeys);
    }

    /** Deterministic, machine-readable schema comparison. Rows are change, object, detail. */
    public static QueryResult diff(SchemaSnapshot before, SchemaSnapshot after) {
        Objects.requireNonNull(before, "before"); Objects.requireNonNull(after, "after");
        List<List<Object>> changes = new ArrayList<>();
        java.util.Set<String> names = new java.util.TreeSet<>();
        names.addAll(before.columns().keySet()); names.addAll(after.columns().keySet());
        for (String name : names) {
            List<Column> oldColumns = before.columns().get(name), newColumns = after.columns().get(name);
            if (oldColumns == null) { changes.add(List.of("added", "table", name)); continue; }
            if (newColumns == null) { changes.add(List.of("removed", "table", name)); continue; }
            Map<String, Column> oldByName = byColumn(oldColumns), newByName = byColumn(newColumns);
            java.util.Set<String> columnNames = new java.util.TreeSet<>(); columnNames.addAll(oldByName.keySet()); columnNames.addAll(newByName.keySet());
            for (String column : columnNames) {
                Column oldColumn = oldByName.get(column), newColumn = newByName.get(column);
                if (oldColumn == null) changes.add(List.of("added", "column", name + "." + column));
                else if (newColumn == null) changes.add(List.of("removed", "column", name + "." + column));
                else if (!oldColumn.equals(newColumn)) changes.add(List.of("changed", "column", name + "." + column));
            }
        }
        diffSet(changes, "key", before.keys(), after.keys());
        diffSet(changes, "index", before.indexes(), after.indexes());
        diffSet(changes, "foreign_key", before.foreignKeys(), after.foreignKeys());
        return new QueryResult(List.of("change", "object", "detail"), changes, -1);
    }
    private static Map<String, Column> byColumn(List<Column> columns) { Map<String, Column> map = new LinkedHashMap<>(); for (Column c : columns) map.put(c.name(), c); return map; }
    private static void diffSet(List<List<Object>> changes, String kind, List<?> before, List<?> after) {
        java.util.Set<String> oldSet = before.stream().map(String::valueOf).collect(java.util.stream.Collectors.toCollection(java.util.TreeSet::new));
        java.util.Set<String> newSet = after.stream().map(String::valueOf).collect(java.util.stream.Collectors.toCollection(java.util.TreeSet::new));
        for (String value : newSet) if (!oldSet.contains(value)) changes.add(List.of("added", kind, value));
        for (String value : oldSet) if (!newSet.contains(value)) changes.add(List.of("removed", kind, value));
    }

    private static List<List<Object>> rows(QueryResult r) { return r.rows(); }
    private static String text(List<Object> r, int i) { return r.get(i) == null ? "" : String.valueOf(r.get(i)); }
    private static String nullableText(List<Object> r, int i) { return r.get(i) == null ? null : String.valueOf(r.get(i)); }
    private static boolean isTableType(String type) { return "TABLE".equalsIgnoreCase(type) || "BASE TABLE".equalsIgnoreCase(type); }
    private static boolean isSystemSchema(String schema) {
        if (schema == null) return false;
        String upper = schema.toUpperCase(Locale.ROOT);
        return upper.equals("INFORMATION_SCHEMA") || upper.equals("SYSTEM") || upper.equals("SYS") || upper.startsWith("PG_");
    }
    private static int number(List<Object> r, int i) { return r.get(i) instanceof Number n ? n.intValue() : 0; }
    private static boolean bool(List<Object> r, int i) { return r.get(i) instanceof Boolean b ? b : Boolean.parseBoolean(text(r, i)); }

    public void exportCsv(QueryResult result, Path file) {
        try (Writer writer = Files.newBufferedWriter(file, StandardCharsets.UTF_8)) { writer.write(ResultFormats.csv(result)); }
        catch (IOException e) { throw new DatabaseException("cannot write export"); }
    }
    public void exportJson(QueryResult result, Path file) {
        try (Writer writer = Files.newBufferedWriter(file, StandardCharsets.UTF_8)) { writer.write(ResultFormats.json(result)); }
        catch (IOException e) { throw new DatabaseException("cannot write export"); }
    }
    public static String table(QueryResult result) { return ResultFormats.table(result); }
    public static String csv(QueryResult result) { return ResultFormats.csv(result); }
    public static String json(QueryResult result) { return ResultFormats.json(result); }

    public Connection connection() { ensureOpen(); return connection; }
    private void ensureOpen() { if (closed) throw new IllegalStateException("database is closed"); }
    @Override public void close() {
        if (!closed) try { connection.close(); } catch (SQLException e) { throw DatabaseException.from(e); } finally { closed = true; }
    }
}
