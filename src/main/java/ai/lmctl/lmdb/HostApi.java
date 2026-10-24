package ai.lmctl.lmdb;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;

/** One declaration catalog drives the schema and, after SDK binding, every callback. */
public final class HostApi {
    public record Binding(String type, String name, List<String> parameters, String returns) {
        public String signature() {
            return (type == null ? "fn " : "method " + type + ".") + name + "(" + String.join(", ", parameters) + ") -> " + returns;
        }
    }
    private static Binding function(String name, String returns, String... parameters) { return new Binding(null,name,List.of(parameters),returns); }
    private static Binding method(String type,String name,String returns,String... parameters) { return new Binding(type,name,List.of(parameters),returns); }
    public static final List<Binding> BINDINGS = List.of(
        function("connect", "Connection", "string"),
        function("connect_file", "Connection", "string", "string"),
        method("Connection", "exec", "void", "string"),
        method("Connection", "query", "Result", "string"),
        method("Connection", "schemas", "Result"),
        method("Connection", "tables", "Result"),
        method("Connection", "views", "Result"),
        method("Connection", "columns", "Result", "string"),
        method("Connection", "keys", "Result", "string"),
        method("Connection", "foreign_keys", "Result", "string"),
        method("Connection", "indexes", "Result", "string"),
        method("Connection", "explain", "Result", "string"),
        method("Connection", "diff", "Result", "Connection"),
        method("Connection", "begin", "void"),
        method("Connection", "commit", "void"),
        method("Connection", "rollback", "void"),
        method("Connection", "close", "void"),
        method("Result", "csv", "void", "string"),
        method("Result", "json", "void", "string"),
        method("Result", "csv_string", "string"),
        method("Result", "json_string", "string"),
        method("Result", "table", "string"),
        method("Result", "rows", "int"),
        method("Result", "columns", "int"),
        method("Result", "column", "string", "int"),
        method("Result", "number", "float", "int", "int"),
        method("Result", "text", "string", "int", "int"),
        method("Result", "is_null", "bool", "int", "int")
    );
    private HostApi() {}
    public static String signatures() { return String.join("\n", BINDINGS.stream().map(Binding::signature).sorted().toList()) + "\n"; }
    public static byte[] schemaBytes() { return schema().getBytes(java.nio.charset.StandardCharsets.UTF_8); }
    public static String schema() {
        var types = new LinkedHashMap<String,List<Binding>>();
        var functions = new ArrayList<Binding>();
        for (var binding : BINDINGS) {
            if (binding.type() == null) functions.add(binding);
            else types.computeIfAbsent(binding.type(), key -> new ArrayList<>()).add(binding);
        }
        StringBuilder out = new StringBuilder("{\"dsl.schema\":2,\"name\":\"lmdb\",\"types\":{");
        boolean first = true;
        for (var type : types.entrySet()) {
            if (!first) out.append(','); first = false;
            out.append(quote(type.getKey())).append(":{\"methods\":{");
            appendBindings(out,type.getValue()); out.append("}}");
        }
        out.append("},\"functions\":{"); appendBindings(out,functions);
        return out.append("},\"context\":{}}\n").toString();
    }
    private static void appendBindings(StringBuilder out,List<Binding> bindings) {
        boolean first = true;
        for (var binding : bindings) {
            if (!first) out.append(','); first = false;
            out.append(quote(binding.name())).append(":[{\"params\":[");
            out.append(String.join(",",binding.parameters().stream().map(HostApi::quote).toList()));
            out.append("],\"returns\":").append(quote(binding.returns())).append("}]");
        }
    }
    private static String quote(String value) { return "\"" + value + "\""; }
}
