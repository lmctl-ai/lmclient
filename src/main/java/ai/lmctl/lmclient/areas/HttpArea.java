package ai.lmctl.lmclient.areas;

import io.lmctl.lmcode.Json;
import java.io.ByteArrayOutputStream;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;

/** HTTP Request connector. No redirects/retries; bounded bodies and complete-response deadlines. */
public final class HttpArea {
    private HttpArea() {}
    public static final int MAX_BODY_BYTES = 10 * 1024 * 1024;
    private static final class Failure extends RuntimeException {
        final String code;
        Failure(String code, String message) { super(message); this.code = code; }
    }
    private static Failure fail(String code, String message) { return new Failure(code, message); }
    private static Failure usage(String message) { return fail("USAGE", message); }
    private record Options(URI url, String method, Map<String,String> headers, String body, String service, int timeout) {}
    private record Auth(String token, String source) {}

    public static int run(String[] args) {
        try {
            Options o = parse(args);
            List<String> secrets = new ArrayList<>();
            for (var h : o.headers.entrySet()) {
                if (Set.of("authorization", "proxy-authorization", "cookie").contains(h.getKey())) {
                    secret(secrets, h.getValue());
                    if (h.getKey().endsWith("authorization") && h.getValue().contains(" "))
                        secret(secrets, h.getValue().substring(h.getValue().indexOf(' ') + 1));
                }
            }
            Auth auth = o.service == null ? new Auth(null, null) : resolveAuth(o.service, o.timeout, secrets);
            if (auth.token != null) o.headers.put("authorization", "Bearer " + auth.token);
            long start = System.nanoTime();
            HttpResponse<byte[]> response = exchange(o.url, o.method, o.headers, o.body, o.timeout);
            String text = new String(response.body(), StandardCharsets.UTF_8);
            Map<String,Object> result = new LinkedHashMap<>();
            result.put("status", response.statusCode());
            result.put("ok", response.statusCode() < 400);
            result.put("contentType", response.headers().firstValue("content-type").orElse(null));
            result.put("latencyMs", (System.nanoTime() - start) / 1_000_000);
            result.put("url", response.uri().toString());
            if (auth.source != null) result.put("keySource", auth.source);
            try { result.put("bodyJson", Json.parse(text)); }
            catch (IllegalArgumentException e) { result.put("bodyText", text); }
            return Envelope.ok(json(result, secrets));
        } catch (Failure e) { return Envelope.fail(e.code, e.getMessage()); }
        catch (IllegalArgumentException e) { return Envelope.fail("USAGE", "invalid HTTP request options"); }
        catch (Exception e) { return Envelope.fail("HTTP_ERROR", "HTTP request failed; check local files and credential storage"); }
    }

    private static Options parse(String[] args) throws Exception {
        if (args.length == 0 || !args[0].equals("request")) throw usage("usage: lmclient http request URL [--method M] [--header 'N: V'] [--data STRING | --data-file PATH] [--auth SERVICE] [--timeout MS]");
        String url = null, method = null, body = null, file = null, service = null;
        int timeout = 30000;
        Map<String,String> headers = new LinkedHashMap<>();
        for (int i = 1; i < args.length; i++) {
            String a = args[i];
            if (!a.startsWith("--")) {
                if (url != null) throw usage("unexpected positional argument");
                url = a; continue;
            }
            if (!Set.of("--method", "--header", "--data", "--data-file", "--auth", "--timeout").contains(a)) throw usage("unknown HTTP option");
            if (++i >= args.length) throw usage("missing HTTP option value");
            String value = args[i];
            switch (a) {
                case "--method" -> method = value.toUpperCase(Locale.ROOT);
                case "--data" -> body = value;
                case "--data-file" -> file = value;
                case "--auth" -> service = value;
                case "--timeout" -> {
                    try { timeout = Integer.parseInt(value); } catch (NumberFormatException e) { throw usage("--timeout must be a positive integer (ms)"); }
                    if (timeout < 1) throw usage("--timeout must be a positive integer (ms)");
                }
                case "--header" -> {
                    int colon = value.indexOf(':');
                    if (colon < 1) throw usage("header must look like Name: value");
                    String name = value.substring(0, colon).trim().toLowerCase(Locale.ROOT);
                    String content = value.substring(colon + 1).trim();
                    if (!name.matches("[!#$%&'*+.^_`|~0-9a-z-]+") || content.contains("\r") || content.contains("\n")) throw usage("invalid HTTP header");
                    headers.merge(name, content, (old, next) -> old + ", " + next);
                }
            }
        }
        URI uri = uri(url);
        if (body != null && file != null) throw usage("use only one of --data and --data-file");
        if (file != null) {
            try {
                if (Files.size(Path.of(file)) > MAX_BODY_BYTES) throw usage("data file exceeds 10 MiB");
                body = Files.readString(Path.of(file), StandardCharsets.UTF_8);
            } catch (java.io.IOException e) { throw usage("cannot read --data-file"); }
        }
        if (method == null) method = body == null ? "GET" : "POST";
        if (!method.matches("[!#$%&'*+.^_`|~0-9A-Z-]+")) throw usage("invalid HTTP method");
        if (body != null && !headers.containsKey("content-type")) {
            String type = "text/plain; charset=utf-8";
            try { Json.parse(body); type = "application/json"; } catch (IllegalArgumentException ignored) { }
            headers.put("content-type", type);
        }
        headers.putIfAbsent("accept", "application/json, text/*;q=0.9, */*;q=0.8");
        if (method.equals("GET") || method.equals("HEAD")) body = null;
        return new Options(uri, method, headers, body, service, timeout);
    }
    private static URI uri(String value) {
        try {
            URI uri = URI.create(value);
            if (!Set.of("http", "https").contains(uri.getScheme()) || uri.getHost() == null || uri.getUserInfo() != null)
                throw usage("URL must be absolute HTTP(S) without embedded credentials");
            return uri;
        } catch (NullPointerException | IllegalArgumentException e) { throw usage("URL must be absolute HTTP(S) without embedded credentials"); }
    }

    private static Auth resolveAuth(String service, int timeout, List<String> secrets) {
        for (String field : List.of("api_key", "oauth_access_token", "oauth_refresh_token", "oauth_client_secret")) secret(secrets, CredStore.get(service, field));
        String token = CredStore.get(service, "api_key");
        if (present(token)) return new Auth(token, "store");
        String envName = service.toUpperCase(Locale.ROOT).replaceAll("[^A-Z0-9]", "_") + "_API_KEY";
        token = System.getenv(envName);
        if (present(token)) { secret(secrets, token); return new Auth(token, "env:" + envName); }
        token = CredStore.get(service, "oauth_access_token");
        if (!present(token)) throw fail("MISSING_KEY", "configure an API key with lmclient cred set " + service + " api_key or connect with lmclient oauth authorize " + service);
        String expiry = CredStore.get(service, "oauth_expires_at");
        boolean expired = false;
        if (present(expiry)) {
            try { expired = !Instant.parse(expiry).isAfter(Instant.now()); }
            catch (RuntimeException e) { expired = true; }
        }
        if (expired) token = refreshOAuth(service, timeout);
        secret(secrets, token);
        secret(secrets, CredStore.get(service, "oauth_refresh_token"));
        return new Auth(token, "store-oauth");
    }
    private static Failure reconnect(String service) { return fail("RECONNECT", "OAuth authorization expired or revoked; run lmclient oauth authorize " + service + " again"); }

    /** Shared credential-field contract; does not depend on the concurrently implemented OAuth area. */
    public static String refreshOAuth(String service, int timeout) {
        String refresh = CredStore.get(service, "oauth_refresh_token");
        if (!present(refresh)) throw reconnect(service);
        try {
            String endpoint = CredStore.get(service, "oauth_token_url");
            String id = CredStore.get(service, "oauth_client_id");
            String secret = Objects.requireNonNullElse(CredStore.get(service, "oauth_client_secret"), "");
            String style = CredStore.get(service, "oauth_auth_style");
            if (!present(style)) style = "header";
            if (!present(id) || !Set.of("header", "body").contains(style)) throw new IllegalArgumentException();
            Map<String,String> headers = new LinkedHashMap<>();
            headers.put("content-type", "application/x-www-form-urlencoded");
            headers.put("accept", "application/json");
            String body = "grant_type=refresh_token&refresh_token=" + encode(refresh);
            if (style.equals("header")) headers.put("authorization", "Basic " + Base64.getEncoder().encodeToString((id + ":" + secret).getBytes(StandardCharsets.UTF_8)));
            else body += "&client_id=" + encode(id) + "&client_secret=" + encode(secret);
            HttpResponse<byte[]> response = exchange(uri(endpoint), "POST", headers, body, timeout);
            Map<String,Object> data = Json.object(Json.parse(response.body()));
            if ("invalid_grant".equals(data.get("error"))) throw reconnect(service);
            if (response.statusCode() < 200 || response.statusCode() >= 300 || data.get("error") != null || !(data.get("access_token") instanceof String access) || access.isEmpty()) throw new IllegalArgumentException();
            String expiresAt = null;
            if (data.containsKey("expires_in")) {
                Object expires = data.get("expires_in");
                double seconds = expires == null ? 0 : Double.parseDouble(expires.toString());
                if (!Double.isFinite(seconds) || seconds < 0 || seconds > (8.64e15 - System.currentTimeMillis()) / 1000) throw new IllegalArgumentException();
                expiresAt = Instant.ofEpochMilli(System.currentTimeMillis() + (long)(seconds * 1000)).toString();
            }
            CredStore.set(service, "oauth_access_token", access);
            if (data.get("refresh_token") instanceof String rotated && !rotated.isEmpty()) CredStore.set(service, "oauth_refresh_token", rotated);
            if (expiresAt == null) CredStore.delete(service, "oauth_expires_at"); else CredStore.set(service, "oauth_expires_at", expiresAt);
            for (String field : List.of("token_type", "scope")) if (data.get(field) instanceof String value) CredStore.set(service, "oauth_" + field, value);
            return access;
        } catch (Failure e) {
            if (e.code.equals("RECONNECT")) throw e;
            throw fail("OAUTH_REFRESH", "OAuth token refresh failed");
        } catch (Exception e) { throw fail("OAUTH_REFRESH", "OAuth token refresh failed"); }
    }
    private static String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
    private static boolean present(String value) { return value != null && !value.isEmpty(); }
    private static void secret(List<String> secrets, String value) { if (present(value)) secrets.add(value); }

    private static HttpResponse<byte[]> exchange(URI url, String method, Map<String,String> headers, String body, int timeout) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(url).timeout(Duration.ofMillis(timeout));
        try { headers.forEach(builder::header); }
        catch (IllegalArgumentException e) { throw usage("invalid or JDK-restricted HTTP header"); }
        HttpRequest request;
        try { request = builder.method(method, body == null ? HttpRequest.BodyPublishers.noBody() : HttpRequest.BodyPublishers.ofString(body, StandardCharsets.UTF_8)).build(); }
        catch (IllegalArgumentException e) { throw usage("invalid or unsupported HTTP method"); }
        HttpClient client = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
            .followRedirects(HttpClient.Redirect.NEVER).connectTimeout(Duration.ofMillis(timeout)).build();
        CompletableFuture<HttpResponse<byte[]>> pending = null;
        try {
            pending = client.sendAsync(request, info -> new LimitedBody());
            return pending.get(timeout, TimeUnit.MILLISECONDS);
        } catch (TimeoutException e) {
            if (pending != null) pending.cancel(true);
            throw fail("TIMEOUT", "HTTP request timed out");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            if (pending != null) pending.cancel(true);
            throw fail("NETWORK", "HTTP request interrupted");
        } catch (ExecutionException e) {
            for (Throwable cause = e; cause != null; cause = cause.getCause()) {
                if (cause instanceof Failure failure) throw failure;
                if (cause instanceof java.net.http.HttpTimeoutException) throw fail("TIMEOUT", "HTTP request timed out");
            }
            throw fail("NETWORK", "HTTP request failed");
        } finally { client.shutdownNow(); }
    }

    private static final class LimitedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> future = new CompletableFuture<>();
        private final ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody() { return future; }
        public void onSubscribe(Flow.Subscription value) { subscription = value; value.request(1); }
        public void onNext(List<ByteBuffer> chunks) {
            for (ByteBuffer chunk : chunks) {
                if (chunk.remaining() > MAX_BODY_BYTES - buffer.size()) {
                    subscription.cancel(); future.completeExceptionally(fail("BODY_TOO_LARGE", "HTTP response exceeds 10 MiB")); return;
                }
                byte[] bytes = new byte[chunk.remaining()]; chunk.get(bytes); buffer.writeBytes(bytes);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { future.completeExceptionally(error); }
        public void onComplete() { future.complete(buffer.toByteArray()); }
    }

    private static String json(Object value, List<String> secrets) {
        if (value == null) return "null";
        if (value instanceof String text) {
            for (String secret : secrets) text = text.replace(secret, "[REDACTED]");
            return Envelope.quote(text);
        }
        if (value instanceof Map<?,?> map) {
            StringJoiner fields = new StringJoiner(",", "{", "}");
            map.forEach((k,v) -> fields.add(json(k.toString(), secrets) + ":" + json(v, secrets)));
            return fields.toString();
        }
        if (value instanceof List<?> list) {
            StringJoiner items = new StringJoiner(",", "[", "]");
            for (Object item : list) items.add(json(item, secrets));
            return items.toString();
        }
        if (value instanceof Double n && !Double.isFinite(n)) return "null";
        return value.toString();
    }
}
