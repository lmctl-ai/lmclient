package ai.lmctl.lmclient.areas;

import io.lmctl.lmcode.Json;
import java.io.*;
import java.net.URI;
import java.net.http.*;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

/** lmconn-compatible providers/chat/probe; fixed argv, bounded I/O, no secret output. */
public final class LlmArea {
    private LlmArea() {}
    private record Provider(String kind, String base, String env, String model, List<String> command, int timeout) {}
    private record Key(String value, String source) {}
    private static final Map<String,Provider> PROVIDERS = new LinkedHashMap<>();
    static {
        PROVIDERS.put("deepseek", new Provider("api", "https://api.deepseek.com", "DEEPSEEK_API_KEY", "deepseek-flash", null, 120000));
        PROVIDERS.put("openrouter", new Provider("api", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "nvidia/nemotron-3.5-lightning:free", null, 120000));
        PROVIDERS.put("ollama-cloud", new Provider("api", "https://ollama.com/v1", "OLLAMA_API_KEY", "gpt-oss:20b-cloud", null, 120000));
        PROVIDERS.put("claude", cli(List.of("claude", "-p"), 180000));
        PROVIDERS.put("codex", cli(List.of("codex", "exec", "--skip-git-repo-check"), 240000));
        PROVIDERS.put("agy", cli(List.of("agy", "-p"), 180000));
        PROVIDERS.put("kimi", cli(List.of("kimi", "-p"), 180000));
    }
    private static Provider cli(List<String> command, int timeout) { return new Provider("cli", null, null, null, command, timeout); }
    private static final class Failure extends RuntimeException {
        final String code;
        Failure(String code, String message) { super(message); this.code = code; }
    }
    private static Failure failure(String code, String message) { return new Failure(code, message); }
    private static Failure usage(String message) { return failure("USAGE", message); }
    private static Provider provider(String name) {
        Provider p = PROVIDERS.get(name);
        if (p == null) throw usage("unknown provider; known providers: " + String.join(", ", PROVIDERS.keySet()));
        return p;
    }
    private static Key key(String name, Provider p) {
        if (p.env == null) return new Key(null, "none");
        String value = CredStore.get(name, "api_key");
        if (value != null && !value.isEmpty()) return new Key(value, "store");
        value = System.getenv(p.env);
        return value == null || value.isEmpty() ? new Key(null, "missing") : new Key(value, "env:" + p.env);
    }

    public static int run(String[] args) {
        Redactor redactor = new Redactor();
        try {
            if (args.length == 0) throw usage("usage: lmclient llm <providers|chat|probe>");
            Object result;
            switch (args[0]) {
                case "providers" -> {
                    if (args.length != 1) throw usage("usage: lmclient llm providers");
                    List<Object> list = new ArrayList<>();
                    for (var entry : PROVIDERS.entrySet()) {
                        Provider p = entry.getValue(); Key key = key(entry.getKey(), p); redactor.add(key.value);
                        Map<String,Object> row = new LinkedHashMap<>();
                        row.put("name", entry.getKey()); row.put("kind", p.kind); row.put("defaultModel", p.model); row.put("key", key.source);
                        list.add(row);
                    }
                    result = list;
                }
                case "chat" -> {
                    if (args.length < 2) throw usage("llm chat requires a provider");
                    Provider p = provider(args[1]);
                    Map<String,String> options = options(args);
                    int timeout = positive(options.getOrDefault("--timeout", Integer.toString(p.timeout)), "--timeout");
                    int maxTokens = positive(options.getOrDefault("--max-tokens", "256"), "--max-tokens");
                    String prompt = options.get("--prompt");
                    if (options.containsKey("--prompt-file")) {
                        try (InputStream input = Files.newInputStream(Path.of(options.get("--prompt-file")))) { prompt = inputText(input, 1024 * 1024); }
                        catch (IOException e) { throw usage("cannot read --prompt-file"); }
                    }
                    if (prompt == null) prompt = inputText(System.in, 1024 * 1024);
                    result = chat(args[1], p, prompt, options.get("--system"), options.get("--model"), maxTokens, timeout, redactor);
                }
                case "probe" -> {
                    List<String> names = args.length == 1 ? new ArrayList<>(PROVIDERS.keySet()) : Arrays.asList(args).subList(1, args.length);
                    names.forEach(LlmArea::provider);
                    List<Object> list = new ArrayList<>();
                    for (String name : names) {
                        Provider p = provider(name); long started = System.nanoTime();
                        Map<String,Object> row = new LinkedHashMap<>();
                        row.put("provider", name); row.put("kind", p.kind); row.put("ok", false); row.put("reply", ""); row.put("error", null);
                        try {
                            Map<String,Object> reply = chat(name, p, "Reply with exactly: pong", null, null, 200, p.timeout, redactor);
                            row.put("reply", excerpt(redactor.clean((String)reply.get("text")), 80)); row.put("ok", true);
                        } catch (Failure e) { row.put("error", redactor.clean(e.getMessage())); }
                        catch (Exception e) { row.put("error", "provider request failed"); }
                        row.put("latencyMs", elapsed(started)); list.add(row);
                    }
                    result = list;
                }
                default -> throw usage("usage: lmclient llm <providers|chat|probe>");
            }
            return Envelope.ok(json(result, redactor));
        } catch (Failure e) { return Envelope.fail(e.code, redactor.clean(e.getMessage())); }
        catch (InterruptedException e) { Thread.currentThread().interrupt(); return Envelope.fail("LLM_ERROR", "provider request interrupted"); }
        catch (Exception e) { return Envelope.fail("LLM_ERROR", "LLM command failed"); }
    }
    private static Map<String,String> options(String[] args) {
        Map<String,String> options = new HashMap<>();
        for (int i = 2; i < args.length; i++) {
            String flag = args[i];
            if (!Set.of("--model", "--system", "--max-tokens", "--prompt", "--prompt-file", "--stdin", "--timeout").contains(flag)) throw usage("unknown chat option");
            if (options.containsKey(flag)) throw usage("duplicate chat option");
            if (flag.equals("--stdin")) options.put(flag, "true");
            else {
                if (++i >= args.length || args[i].startsWith("--")) throw usage("missing chat option value");
                options.put(flag, args[i]);
            }
        }
        if (List.of("--prompt", "--prompt-file", "--stdin").stream().filter(options::containsKey).count() > 1) throw usage("choose only one of --prompt, --prompt-file, --stdin");
        return options;
    }
    private static int positive(String value, String flag) {
        try { int n = Integer.parseInt(value); if (n > 0) return n; } catch (NumberFormatException ignored) { }
        throw usage(flag + " must be a positive integer");
    }
    private static String inputText(InputStream input, int cap) throws IOException {
        byte[] bytes = input.readNBytes(cap + 1);
        if (bytes.length > cap) throw failure("OUTPUT_TOO_LARGE", "input or provider output exceeds its byte limit");
        return new String(bytes, StandardCharsets.UTF_8);
    }
    private static long elapsed(long start) { return (System.nanoTime() - start) / 1_000_000; }
    private static long remaining(long deadline) {
        long value = TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime());
        if (value <= 0) throw failure("TIMEOUT", "provider request timed out");
        return value;
    }
    private static String excerpt(String text, int max) { return text.substring(0, Math.min(max, text.length())); }

    private static Map<String,Object> chat(String name, Provider p, String prompt, String system, String model, int maxTokens, int timeout, Redactor redactor) throws Exception {
        long start = System.nanoTime(); long deadline = start + TimeUnit.MILLISECONDS.toNanos(timeout);
        Map<String,Object> result = new LinkedHashMap<>();
        if (p.kind.equals("api")) {
            Key key = key(name, p); redactor.add(key.value);
            if (key.value == null) throw failure("MISSING_KEY", "no API key configured for " + name);
            String selected = model == null ? p.model : model;
            Map<String,Object> payload = new LinkedHashMap<>();
            payload.put("model", selected); payload.put("max_tokens", maxTokens);
            List<Object> messages = new ArrayList<>();
            if (system != null) messages.add(Map.of("role", "system", "content", system));
            messages.add(Map.of("role", "user", "content", prompt)); payload.put("messages", messages);
            String override = System.getenv("LMCLIENT_LLM_" + name.toUpperCase(Locale.ROOT).replace('-', '_') + "_BASE_URL");
            URI endpoint;
            try {
                endpoint = URI.create((override == null ? p.base : override).replaceAll("/+$", "") + "/chat/completions");
                if (!Set.of("http", "https").contains(endpoint.getScheme()) || endpoint.getHost() == null || endpoint.getUserInfo() != null || endpoint.getQuery() != null || endpoint.getFragment() != null) throw new IllegalArgumentException();
            } catch (Exception e) { throw usage("invalid provider base URL override"); }
            HttpClient client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).followRedirects(HttpClient.Redirect.NEVER)
                .connectTimeout(Duration.ofMillis(timeout)).build();
            HttpResponse<byte[]> response;
            try {
                for (int attempt = 0; ; attempt++) {
                    long left = remaining(deadline);
                    HttpRequest request = HttpRequest.newBuilder(endpoint).timeout(Duration.ofMillis(left))
                        .header("Content-Type", "application/json").header("Authorization", "Bearer " + key.value)
                        .POST(HttpRequest.BodyPublishers.ofString(json(payload, null), StandardCharsets.UTF_8)).build();
                    CompletableFuture<HttpResponse<byte[]>> pending = client.sendAsync(request, info -> new LimitedBody());
                    try { response = pending.get(left, TimeUnit.MILLISECONDS); }
                    catch (TimeoutException e) { pending.cancel(true); throw failure("TIMEOUT", "provider request timed out"); }
                    catch (ExecutionException e) {
                        for (Throwable c = e; c != null; c = c.getCause()) {
                            if (c instanceof Failure f) throw f;
                            if (c instanceof HttpTimeoutException) throw failure("TIMEOUT", "provider request timed out");
                        }
                        throw failure("API_ERROR", "provider request failed");
                    }
                    if (response.statusCode() != 429 || attempt == 1) break;
                    if (remaining(deadline) <= 3000) throw failure("TIMEOUT", "provider retry exceeds request deadline");
                    Thread.sleep(3000);
                }
            } finally { client.shutdownNow(); }
            String text = new String(response.body(), StandardCharsets.UTF_8);
            if (response.statusCode() < 200 || response.statusCode() >= 300)
                throw failure("HTTP_ERROR", "HTTP " + response.statusCode() + ": " + excerpt(redactor.clean(text).replaceAll("\\s+", " "), 300));
            Map<String,Object> data;
            try { data = Json.object(Json.parse(text)); }
            catch (IllegalArgumentException e) { throw failure("API_ERROR", "provider returned invalid JSON"); }
            Object content;
            try { content = Json.object(Json.object(Json.array(data.get("choices")).getFirst()).get("message")).get("content"); }
            catch (RuntimeException e) { throw failure("INVALID_RESPONSE", "provider response has no assistant text"); }
            if (!(content instanceof String)) throw failure("INVALID_RESPONSE", "provider response has no assistant text");
            result.put("text", content); result.put("model", data.get("model") == null ? selected : data.get("model"));
            result.put("usage", data.get("usage")); result.put("keySource", key.source);
        } else {
            // CLI subprocesses inherit environment; redact its secret-shaped entries and stored API keys.
            for (var entry : PROVIDERS.entrySet()) if (entry.getValue().env != null) redactor.add(CredStore.get(entry.getKey(), "api_key"));
            List<String> argv = new ArrayList<>(p.command);
            argv.add(system == null ? prompt : system + "\n\n" + prompt);
            Process child;
            try { child = new ProcessBuilder(argv).directory(Path.of(System.getProperty("java.io.tmpdir")).toFile()).start(); }
            catch (IOException e) { throw failure("CLI_ERROR", "provider " + name + " could not start"); }
            try (ExecutorService readers = Executors.newVirtualThreadPerTaskExecutor()) {
                child.getOutputStream().close();
                Future<String> stdout = readers.submit(() -> capture(child.getInputStream(), child));
                Future<String> stderr = readers.submit(() -> capture(child.getErrorStream(), child));
                try {
                    if (!child.waitFor(remaining(deadline), TimeUnit.MILLISECONDS)) throw failure("TIMEOUT", "provider " + name + " timed out");
                    String out = stdout.get(remaining(deadline), TimeUnit.MILLISECONDS);
                    String err = stderr.get(remaining(deadline), TimeUnit.MILLISECONDS);
                    if (child.exitValue() != 0) throw failure("CLI_ERROR", "provider " + name + " exited with code " + child.exitValue() + (err.isEmpty() ? "" : ": " + excerpt(redactor.clean(err), 500)));
                    result.put("text", out.strip()); result.put("model", null); result.put("keySource", "none");
                } catch (TimeoutException e) { throw failure("TIMEOUT", "provider " + name + " timed out"); }
                catch (ExecutionException e) {
                    if (e.getCause() instanceof Failure f) throw f;
                    throw failure("CLI_ERROR", "provider output could not be read");
                } finally {
                    kill(child); stdout.cancel(true); stderr.cancel(true);
                    try { child.getInputStream().close(); child.getErrorStream().close(); } catch (IOException ignored) { }
                }
            } finally { kill(child); }
        }
        result.put("latencyMs", elapsed(start)); result.put("provider", name);
        return result;
    }
    private static String capture(InputStream stream, Process child) throws IOException {
        try { return inputText(stream, 2 * 1024 * 1024); }
        catch (Failure e) { kill(child); throw e; }
    }
    private static void kill(Process child) {
        child.descendants().forEach(ProcessHandle::destroyForcibly);
        if (child.isAlive()) child.destroyForcibly();
    }
    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> future = new CompletableFuture<>();
        private final ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody() { return future; }
        public void onSubscribe(Flow.Subscription s) { subscription = s; s.request(1); }
        public void onNext(List<ByteBuffer> chunks) {
            for (ByteBuffer chunk : chunks) {
                if (chunk.remaining() > 10 * 1024 * 1024 - bytes.size()) {
                    subscription.cancel(); future.completeExceptionally(failure("OUTPUT_TOO_LARGE", "provider response exceeds 10 MiB")); return;
                }
                byte[] part = new byte[chunk.remaining()]; chunk.get(part); bytes.writeBytes(part);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { future.completeExceptionally(error); }
        public void onComplete() { future.complete(bytes.toByteArray()); }
    }
    private static final class Redactor {
        final Set<String> secrets = new TreeSet<>(Comparator.comparingInt(String::length).reversed().thenComparing(Comparator.naturalOrder()));
        Redactor() { System.getenv().forEach((k,v) -> { if (k.toUpperCase(Locale.ROOT).matches(".*(KEY|TOKEN|PASSWORD|SECRET).*")) add(v); }); }
        void add(String value) { if (value != null && !value.isEmpty()) secrets.add(value); }
        String clean(String value) {
            for (String secret : secrets) value = value.replace(secret, "[REDACTED]");
            return value.replaceAll("(?i)\\bBearer\\s+[^\\s\"'<>;,]+", "Bearer [REDACTED]");
        }
    }
    private static String json(Object value, Redactor redactor) {
        if (value == null) return "null";
        if (value instanceof String text) return Envelope.quote(redactor == null ? text : redactor.clean(text));
        if (value instanceof Map<?,?> map) {
            StringJoiner fields = new StringJoiner(",", "{", "}");
            map.forEach((k,v) -> fields.add(json(k.toString(), redactor) + ":" + json(v, redactor))); return fields.toString();
        }
        if (value instanceof List<?> list) {
            StringJoiner items = new StringJoiner(",", "[", "]");
            for (Object item : list) items.add(json(item, redactor)); return items.toString();
        }
        if (value instanceof Double n && !Double.isFinite(n)) return "null";
        return value.toString();
    }
}
