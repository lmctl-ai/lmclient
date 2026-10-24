package ai.lmctl.lmdb;

import ai.lmctl.lmdb.core.Database;
import io.lmctl.lmcode.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Set;

/** Explicit JDBC callbacks: no runtime reflection or dynamic host class loading. */
public final class DslHost implements AutoCloseable {
    private final List<Database> connections = new ArrayList<>();
    private final Set<Database> nativeConnections = Collections.newSetFromMap(new IdentityHashMap<>());
    private final Registry registry = new Registry();
    private final Context context = new Context();

    public DslHost() {
        context.memoryLimitBytes = Main.memoryBudget();
        for (var binding : HostApi.BINDINGS) {
            Registry.Callback callback = (ctx,self,args) -> {
                try { return call(binding,ctx,self,args); }
                catch (VmException error) { throw error; }
                catch (ai.lmctl.lmdb.core.DatabaseException error) { throw VmException.host(error.getMessage()); }
                catch (Exception error) { throw VmException.host("database or file operation failed (" + error.getClass().getSimpleName() + ")"); }
            };
            if (binding.type() == null) registry.function(binding.name(),binding.parameters(),binding.returns(),callback);
            else registry.method(binding.type(),binding.name(),binding.parameters(),binding.returns(),callback);
        }
        registry.checkSchemaSignatures(HostApi.BINDINGS.stream().map(HostApi.Binding::signature).toList());
    }

    private Value call(HostApi.Binding binding,Context ctx,Value self,Value[] args) throws Exception {
        String name = binding.name();
        if (binding.type() == null) {
            String url = string(args[0]);
            Credentials.validateUrl(url);
            boolean nativeEngine = isNativeEngine(url);
            if (connections.size() >= 64) throw VmException.host("connection limit exceeded (64)");
            if (nativeEngine && nativeConnections.size() >= 2)
                throw VmException.host("embedded native connection limit exceeded (2)");
            Database database = Database.connect(url, Credentials.read(args.length == 2 ? string(args[1]) : System.getenv("LMDB_CREDENTIALS_FILE")));
            try { ctx.charge(4096); } catch (RuntimeException error) { database.close(); throw error; }
            connections.add(database);
            if (nativeEngine) nativeConnections.add(database);
            return Value.object("Connection",database);
        }
        if (binding.type().equals("Connection")) {
            Database database = (Database) self.asObject();
            switch (name) {
                case "exec":
                    for (String sql : ai.lmctl.lmdb.core.SqlScript.split(string(args[0]))) database.query(sql);
                    return Value.none();
                case "begin": database.connection().setAutoCommit(false); return Value.none();
                case "commit": database.connection().commit(); return Value.none();
                case "rollback": database.connection().rollback(); return Value.none();
                case "close": database.close(); connections.remove(database); nativeConnections.remove(database); return Value.none();
                default: break;
            }
            Database.QueryResult result = switch(name) {
                case "query" -> database.query(string(args[0]));
                case "schemas" -> database.schemas();
                case "tables" -> database.tables();
                case "views" -> database.views();
                case "columns" -> database.columns(null,string(args[0]));
                case "keys" -> database.keys(null,string(args[0]));
                case "foreign_keys" -> database.foreignKeys(null,string(args[0]));
                case "indexes" -> database.indexes(null,string(args[0]));
                case "explain" -> database.explain(string(args[0]));
                case "diff" -> Database.diff(database.snapshot(),((Database)args[0].asObject()).snapshot());
                default -> throw VmException.host("unknown connection operation");
            };
            long bytes = 128;
            for (var row : result.rows()) {
                bytes = Math.addExact(bytes,64 + row.size() * 16L);
                for (Object value : row) if (value != null) bytes = Math.addExact(bytes,32 + (value instanceof byte[] data ? data.length : value.toString().length() * 2L));
            }
            ctx.charge(bytes);
            return Value.object("Result",result);
        }
        Database.QueryResult result = (Database.QueryResult) self.asObject();
        return switch (name) {
            case "rows" -> Value.ofInt(result.rows().size());
            case "columns" -> Value.ofInt(result.columns().size());
            case "column" -> Value.ofString(result.columns().get(index(args[0],result.columns().size())));
            case "csv" -> write(string(args[0]), Database.csv(result));
            case "json" -> write(string(args[0]), Database.json(result));
            case "csv_string" -> text(ctx,Database.csv(result));
            case "json_string" -> text(ctx,Database.json(result));
            case "table" -> text(ctx,Database.table(result));
            case "is_null" -> Value.ofBool(cell(result,args) == null);
            case "text" -> text(ctx,cell(result,args) == null ? "" : cell(result,args).toString());
            case "number" -> {
                Object value = cell(result,args);
                if (!(value instanceof Number number)) throw VmException.host("result cell is not numeric");
                yield Value.ofFloat(number.doubleValue());
            }
            default -> throw VmException.host("unknown result operation");
        };
    }

    private static Value text(Context context,String value) { context.charge(value.length() * 2L + 32); return Value.ofString(value); }
    private static Value write(String path,String content) throws Exception { Files.writeString(Path.of(path),content,StandardCharsets.UTF_8); return Value.none(); }
    private static Object cell(Database.QueryResult result,Value[] args) {
        return result.rows().get(index(args[0],result.rows().size())).get(index(args[1],result.columns().size()));
    }
    private static int index(Value value,int size) {
        long index = value.asInt();
        if (index < 0 || index >= size) throw VmException.host("result index out of range");
        return (int) index;
    }
    private static String string(Value value) { return value.asString().toString(); }
    private static boolean isNativeEngine(String url) { String lower = url.toLowerCase(java.util.Locale.ROOT); return lower.startsWith("jdbc:sqlite:") || lower.startsWith("jdbc:duckdb:"); }

    public int run(Path bytecode,boolean dryRun) throws Exception {
        close();
        context.resetBudget();
        Program program;
        try {
            if (Files.size(bytecode) > context.memoryLimitBytes / 4) throw VmException.badBytecode("bytecode exceeds LMDB_MAX_MEMORY_MB budget");
            program = Program.load(Files.readAllBytes(bytecode),HostApi.schemaBytes(),registry);
        }
        catch (VmException error) { return Reports.error("load",error); }
        catch (java.io.IOException error) { return Reports.error("load",VmException.badBytecode("cannot read bytecode file")); }
        if (dryRun) return Reports.ok("{\"dry_run\":true}");
        try { program.run(context,registry); return Reports.ok("null"); }
        catch (VmException error) {
            if (error.getMessage().toLowerCase(java.util.Locale.ROOT).contains("memory"))
                System.err.println("lmdb: LMDB_MAX_MEMORY_MB memory budget exceeded");
            return Reports.error("run",error);
        }
    }

    @Override public void close() {
        for (Database database : connections) { try { database.close(); } catch (RuntimeException ignored) { /* Close remaining handles. */ } }
        connections.clear();
        nativeConnections.clear();
    }
}
