package ai.lmctl.lmclient.areas;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicReference;

/** OAuth2 authorization code + PKCE, refresh and secret-free status; lmconn-compatible storage. */
public final class OauthArea {
    private OauthArea() {}
    private static final List<String> FIELDS = List.of("client-id", "client-secret", "auth-url", "token-url", "scope", "auth-query", "auth-style");
    private static final int MAX_BODY = 1024 * 1024;
    private static final SecureRandom RANDOM = new SecureRandom();

    /** Safe to expose to another area; messages contain no provider response or credential input. */
    public static final class OAuthException extends RuntimeException {
        public final String code;
        OAuthException(String code, String message) { super(message); this.code = code; }
    }
    private static OAuthException error(String code, String message) { return new OAuthException(code, message); }
    private static OAuthException usage() { return error("USAGE", "Usage: oauth authorize SERVICE [options] | refresh SERVICE | status SERVICE"); }
    private static String field(String name) { return "oauth_" + name.replace('-', '_'); }
    private static String value(String s) { return s == null ? "" : s; }
    private static boolean present(String s) { return s != null && !s.isEmpty(); }

    public static int run(String[] args) {
        try {
            if (args.length < 2 || args[1].isEmpty() || args[1].startsWith("-") || !Set.of("authorize", "refresh", "status").contains(args[0])) throw usage();
            Map<String,String> options = new LinkedHashMap<>();
            for (int i = 2; i < args.length; i++) {
                if (args[i].equals("--json")) continue;
                if (!args[0].equals("authorize") || !args[i].startsWith("--")) throw usage();
                String key = args[i].substring(2);
                if (options.containsKey(key)) throw usage();
                if (Set.of("manual", "no-pkce", "auto-follow").contains(key)) options.put(key, "true");
                else if (FIELDS.contains(key) || key.equals("port") || key.equals("timeout")) {
                    if (++i >= args.length || args[i].startsWith("--")) throw usage();
                    options.put(key, args[i]);
                } else throw usage();
            }
            if (options.containsKey("manual") && options.containsKey("auto-follow")) throw usage();
            int port = number(options.getOrDefault("port", "0"), 0, 65535);
            int timeout = number(options.getOrDefault("timeout", "300000"), 1, Integer.MAX_VALUE);
            String result = switch (args[0]) {
                case "status" -> status(args[1]);
                case "refresh" -> refresh(args[1]);
                default -> authorize(args[1], options, port, timeout);
            };
            return Envelope.ok(result);
        } catch (OAuthException e) { return Envelope.fail(e.code, e.getMessage()); }
        catch (Exception e) { return Envelope.fail("OAUTH_ERROR", "OAuth operation failed"); }
    }
    private static int number(String s, int min, int max) {
        try { int n = Integer.parseInt(s); if (n < min || n > max) throw usage(); return n; }
        catch (NumberFormatException e) { throw usage(); }
    }

    private static Map<String,String> config(String service, Map<String,String> options, boolean authorize) throws IOException {
        Map<String,Object> presets;
        try (InputStream in = OauthArea.class.getResourceAsStream("/oauth-presets.json")) {
            if (in == null) throw new IOException();
            presets = Json.object(new String(in.readNBytes(MAX_BODY), StandardCharsets.UTF_8));
        }
        Object found = presets.get(service);
        Map<?,?> preset = found instanceof Map<?,?> map ? map : Map.of();
        Map<String,String> cfg = new LinkedHashMap<>();
        for (String name : FIELDS) {
            String v = options.get(name);
            if (v == null) v = CredStore.get(service, field(name));
            if (v == null && preset.get(name.replace('-', '_')) instanceof String s) v = s;
            cfg.put(name, value(v));
        }
        if (cfg.get("auth-style").isEmpty()) cfg.put("auth-style", "header");
        for (String name : authorize ? List.of("client-id", "token-url", "auth-url") : List.of("client-id", "token-url")) {
            if (cfg.get(name).isEmpty()) throw error("MISSING_CONFIG", "Missing " + field(name) + "; use cred set SERVICE " + field(name) + " --stdin, or configure a service from oauth-presets.json");
        }
        if (!Set.of("header", "body").contains(cfg.get("auth-style"))) throw error("USAGE", "auth-style must be header or body");
        validateEndpoint(cfg.get("token-url"), "oauth_token_url");
        if (authorize) validateEndpoint(cfg.get("auth-url"), "oauth_auth_url");
        return cfg;
    }
    private static URI validateEndpoint(String raw, String label) {
        try {
            URI uri = URI.create(raw);
            if (!Set.of("http", "https").contains(value(uri.getScheme())) || uri.getHost() == null || uri.getUserInfo() != null || uri.getFragment() != null || uri.getPort() > 65535) throw new IllegalArgumentException();
            return uri;
        } catch (IllegalArgumentException e) { throw error("USAGE", label + " must be an HTTP(S) URL without userinfo or fragment"); }
    }
    public static String status(String service) {
        String expires = CredStore.get(service, "oauth_expires_at");
        boolean expired = false;
        if (expires != null) {
            try { expired = !Instant.parse(expires).isAfter(Instant.now()); }
            catch (Exception e) { expired = true; }
        }
        return "{\"service\":" + Envelope.quote(service) + ",\"authorized\":" + present(CredStore.get(service, "oauth_access_token"))
                + ",\"expiresAt\":" + Envelope.quote(expires) + ",\"expired\":" + expired
                + ",\"hasRefreshToken\":" + present(CredStore.get(service, "oauth_refresh_token"))
                + ",\"scope\":" + Envelope.quote(value(CredStore.get(service, "oauth_scope")))
                + ",\"tokenUrl\":" + Envelope.quote(CredStore.get(service, "oauth_token_url")) + "}";
    }
    /** Silent HTTP-area integration hook: stores new tokens and returns metadata JSON only. */
    public static String refresh(String service) {
        try {
            Map<String,String> cfg = config(service, Map.of(), false);
            String token = CredStore.get(service, "oauth_refresh_token");
            if (!present(token)) throw error("RECONNECT", "No refresh token; run oauth authorize again");
            return save(service, cfg, exchange(cfg, Map.of("grant_type", "refresh_token", "refresh_token", token), deadline(30000)), true);
        } catch (OAuthException e) { throw e; }
        catch (SocketTimeoutException e) { throw error("TIMEOUT", "OAuth refresh timed out"); }
        catch (Exception e) { throw error("OAUTH_ERROR", "OAuth refresh failed"); }
    }

    private static String authorize(String service, Map<String,String> options, int port, int timeout) throws Exception {
        Map<String,String> cfg = config(service, options, true);
        String state = random(), verifier = random();
        long until = deadline(timeout);
        CompletableFuture<String> code = new CompletableFuture<>();
        AtomicReference<Socket> browser = new AtomicReference<>();
        AtomicReference<HttpURLConnection> following = new AtomicReference<>();
        try (ServerSocket server = new ServerSocket()) {
            server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"), port));
            String redirect = "http://127.0.0.1:" + server.getLocalPort() + "/callback";
            URI endpoint = URI.create(cfg.get("auth-url"));
            Map<String,String> query = form(endpoint.getRawQuery());
            query.putAll(form(cfg.get("auth-query")));
            for (String key : List.of("code_challenge", "code_challenge_method", "client_secret", "code_verifier", "code", "access_token", "refresh_token", "id_token")) query.remove(key);
            query.putAll(Map.of("response_type", "code", "client_id", cfg.get("client-id"), "redirect_uri", redirect, "scope", cfg.get("scope"), "state", state));
            if (!options.containsKey("no-pkce")) {
                query.put("code_challenge", Base64.getUrlEncoder().withoutPadding().encodeToString(MessageDigest.getInstance("SHA-256").digest(verifier.getBytes(StandardCharsets.US_ASCII))));
                query.put("code_challenge_method", "S256");
            }
            String rawEndpoint = cfg.get("auth-url").split("\\?", 2)[0];
            String authorizeUrl = rawEndpoint + "?" + encode(query);
            daemon(() -> listen(server, redirect, state, until, browser, code));
            if (options.containsKey("manual")) daemon(() -> {
                try {
                    String line = readLine(System.in, 16384);
                    if (line == null) throw error("OAUTH_ERROR", "No redirect URL supplied on stdin");
                    code.complete(callback(line.trim(), redirect, state));
                } catch (Exception e) { code.completeExceptionally(safeCallback(e)); }
            });
            System.err.println("Authorize URL: " + authorizeUrl);
            if (options.containsKey("manual")) System.err.println("Paste the full redirect URL on stdin:");
            if (options.containsKey("auto-follow")) daemon(() -> {
                try {
                    String next = authorizeUrl;
                    for (int hops = 0; hops < 10; hops++) {
                        HttpURLConnection conn = open(next, until); following.set(conn);
                        try {
                            int status = conn.getResponseCode();
                            if (status >= 300 && status <= 399 && conn.getHeaderField("Location") != null) {
                                next = URI.create(next).resolve(conn.getHeaderField("Location")).toString();
                                validateEndpoint(next, "redirect");
                                continue;
                            }
                            readResponse(conn, until);
                            if (!code.isDone()) code.completeExceptionally(error("OAUTH_ERROR", "Automatic authorization did not reach the callback"));
                            return;
                        } finally { conn.disconnect(); }
                    }
                    code.completeExceptionally(error("OAUTH_ERROR", "Too many authorization redirects"));
                } catch (Exception e) { code.completeExceptionally(e instanceof SocketTimeoutException ? error("TIMEOUT", "OAuth authorization timed out") : error("OAUTH_ERROR", "OAuth callback failed")); }
            });
            try {
                String received;
                try { received = code.get(remaining(until), TimeUnit.MILLISECONDS); }
                catch (ExecutionException e) { throw (OAuthException) e.getCause(); }
                Map<String,String> params = new LinkedHashMap<>(Map.of("grant_type", "authorization_code", "code", received, "redirect_uri", redirect));
                if (!options.containsKey("no-pkce")) params.put("code_verifier", verifier);
                String result = save(service, cfg, exchange(cfg, params, until), false);
                respond(browser.get(), 200, "Authorized. You can close this tab.");
                return result;
            } catch (TimeoutException | SocketTimeoutException e) {
                throw error("TIMEOUT", "OAuth authorization timed out");
            } finally {
                respond(browser.get(), 400, "Authorization finished. Return to the CLI.");
                HttpURLConnection conn = following.get(); if (conn != null) conn.disconnect();
            }
        }
    }
    private static void daemon(Runnable task) { Thread thread = new Thread(task, "lmclient-oauth"); thread.setDaemon(true); thread.start(); }
    private static void listen(ServerSocket server, String redirect, String state, long until, AtomicReference<Socket> browser, CompletableFuture<String> code) {
        try {
            while (!code.isDone()) {
                server.setSoTimeout(remaining(until));
                Socket socket = server.accept();
                socket.setSoTimeout(remaining(until));
                try {
                    InputStream in = socket.getInputStream();
                    String line = readLine(in, 8192);
                    int size = 0;
                    for (String header; (header = readLine(in, 8192)) != null && !header.isEmpty();) {
                        size += header.length(); if (size > 16384) throw new IOException();
                        socket.setSoTimeout(remaining(until));
                    }
                    String[] request = line == null ? new String[0] : line.split(" ");
                    if (request.length != 3 || !request[0].equals("GET") || !request[1].startsWith("/callback?")) { respond(socket, 404, "Not found"); continue; }
                    if (!browser.compareAndSet(null, socket)) { respond(socket, 409, "Callback already received"); continue; }
                    try { code.complete(callback(URI.create(redirect).resolve(request[1]).toString(), redirect, state)); }
                    catch (Exception e) { code.completeExceptionally(safeCallback(e)); }
                } catch (Exception e) { socket.close(); throw e; }
            }
        } catch (Exception e) {
            if (!server.isClosed()) code.completeExceptionally(e instanceof SocketTimeoutException ? error("TIMEOUT", "OAuth authorization timed out") : error("OAUTH_ERROR", "OAuth callback failed"));
        }
    }
    private static OAuthException safeCallback(Exception e) { return e instanceof OAuthException oauth ? oauth : error("OAUTH_ERROR", "Invalid OAuth redirect URL"); }
    private static String callback(String raw, String redirect, String state) {
        URI uri = URI.create(raw), expected = URI.create(redirect);
        Map<String,List<String>> params = formLists(uri.getRawQuery());
        if (!Objects.equals(uri.getScheme(), expected.getScheme()) || !Objects.equals(uri.getRawAuthority(), expected.getRawAuthority()) || !"/callback".equals(uri.getPath())
                || !params.getOrDefault("state", List.of()).equals(List.of(state))) throw error("OAUTH_ERROR", "OAuth callback state or redirect mismatch");
        if (params.containsKey("error")) throw error("OAUTH_ERROR", "OAuth authorization was denied");
        List<String> codes = params.getOrDefault("code", List.of());
        if (codes.size() != 1 || codes.get(0).isEmpty()) throw error("OAUTH_ERROR", "OAuth callback is missing a valid code");
        return codes.get(0);
    }
    private static String readLine(InputStream in, int limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        for (int c; (c = in.read()) != -1;) {
            if (c == '\n') return out.toString(StandardCharsets.UTF_8).replaceFirst("\\r$", "");
            if (out.size() >= limit) throw new IOException();
            out.write(c);
        }
        return out.size() == 0 ? null : out.toString(StandardCharsets.UTF_8);
    }
    private static void respond(Socket socket, int status, String message) {
        if (socket == null || socket.isClosed()) return;
        try (socket) {
            byte[] body = message.getBytes(StandardCharsets.UTF_8);
            socket.getOutputStream().write(("HTTP/1.1 " + status + " Response\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: " + body.length + "\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            socket.getOutputStream().write(body);
        } catch (IOException ignored) { }
    }
    private record Token(Map<String,Object> values, String expiresAt) { }
    private static Token exchange(Map<String,String> cfg, Map<String,String> params, long until) throws Exception {
        Map<String,String> body = new LinkedHashMap<>(params);
        HttpURLConnection conn = open(cfg.get("token-url"), until);
        try {
            conn.setRequestMethod("POST"); conn.setDoOutput(true);
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("Content-Type", "application/x-www-form-urlencoded");
            if (cfg.get("auth-style").equals("header")) conn.setRequestProperty("Authorization", "Basic " + Base64.getEncoder().encodeToString((cfg.get("client-id") + ":" + cfg.get("client-secret")).getBytes(StandardCharsets.UTF_8)));
            else { body.put("client_id", cfg.get("client-id")); body.put("client_secret", cfg.get("client-secret")); }
            byte[] bytes = encode(body).getBytes(StandardCharsets.UTF_8);
            conn.setFixedLengthStreamingMode(bytes.length);
            try (OutputStream out = conn.getOutputStream()) { out.write(bytes); }
            int status = conn.getResponseCode();
            String text = readResponse(conn, until);
            Map<String,Object> token;
            try { token = Json.object(text); }
            catch (IllegalArgumentException e) { token = new LinkedHashMap<>(form(text)); }
            if ("invalid_grant".equals(token.get("error"))) throw error("RECONNECT", "OAuth grant rejected; run oauth authorize again");
            if (status < 200 || status >= 300 || token.containsKey("error") || !(token.get("access_token") instanceof String access) || access.isEmpty()) throw error("OAUTH_ERROR", "OAuth token exchange failed");
            for (String key : List.of("refresh_token", "token_type", "scope"))
                if (token.containsKey(key) && (!(token.get(key) instanceof String s) || (key.equals("refresh_token") && s.isEmpty()))) throw error("OAUTH_ERROR", "Invalid OAuth token response");
            String expiry = null;
            if (token.containsKey("expires_in")) {
                Object raw = token.get("expires_in");
                double seconds;
                try { seconds = raw == null ? 0 : raw instanceof Boolean b ? (b ? 1 : 0) : String.valueOf(raw).isBlank() ? 0 : Double.parseDouble(String.valueOf(raw)); }
                catch (Exception e) { throw error("OAUTH_ERROR", "Invalid OAuth expiry"); }
                if (!Double.isFinite(seconds) || seconds < 0 || seconds * 1000 > 8.64e15 - System.currentTimeMillis()) throw error("OAUTH_ERROR", "Invalid OAuth expiry");
                expiry = Instant.ofEpochMilli(System.currentTimeMillis() + (long)(seconds * 1000)).toString();
            }
            return new Token(token, expiry);
        } finally { conn.disconnect(); }
    }
    private static synchronized String save(String service, Map<String,String> cfg, Token response, boolean refresh) {
        Map<String,String> changes = new LinkedHashMap<>();
        FIELDS.forEach(name -> changes.put(field(name), cfg.get(name)));
        Map<String,Object> token = response.values;
        if (token.containsKey("refresh_token")) changes.put("oauth_refresh_token", (String)token.get("refresh_token"));
        else if (!refresh) changes.put("oauth_refresh_token", null);
        changes.put("oauth_expires_at", response.expiresAt);
        changes.put("oauth_token_type", present((String)token.get("token_type")) ? (String)token.get("token_type") : "Bearer");
        if (token.containsKey("scope")) changes.put("oauth_scope", (String)token.get("scope"));
        changes.put("oauth_access_token", (String)token.get("access_token")); // publish the new access token last
        Map<String,String> old = new LinkedHashMap<>();
        changes.keySet().forEach(key -> old.put(key, CredStore.get(service, key)));
        try { changes.forEach((key, v) -> store(service, key, v)); }
        catch (RuntimeException e) {
            old.forEach((key, v) -> { try { store(service, key, v); } catch (RuntimeException ignored) { } });
            throw error("OAUTH_ERROR", "OAuth credential storage failed");
        }
        return "{\"service\":" + Envelope.quote(service) + ",\"expiresAt\":" + Envelope.quote(response.expiresAt)
                + ",\"hasRefreshToken\":" + present(CredStore.get(service, "oauth_refresh_token")) + ",\"scope\":" + Envelope.quote(value(CredStore.get(service, "oauth_scope"))) + "}";
    }
    private static void store(String service, String key, String v) { if (v == null) CredStore.delete(service, key); else CredStore.set(service, key, v); }
    private static HttpURLConnection open(String url, long until) throws IOException {
        HttpURLConnection conn = (HttpURLConnection) URI.create(url).toURL().openConnection();
        conn.setInstanceFollowRedirects(false); conn.setConnectTimeout(remaining(until)); conn.setReadTimeout(remaining(until));
        return conn;
    }
    private static String readResponse(HttpURLConnection conn, long until) throws IOException {
        InputStream input = conn.getResponseCode() >= 400 ? conn.getErrorStream() : conn.getInputStream();
        if (input == null) return "";
        try (input; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            while (true) {
                conn.setReadTimeout(remaining(until));
                int n = input.read(buffer); if (n < 0) break;
                if (out.size() + n > MAX_BODY) throw new IOException();
                out.write(buffer, 0, n);
            }
            return out.toString(StandardCharsets.UTF_8);
        }
    }
    private static long deadline(int ms) { return System.nanoTime() + ms * 1_000_000L; }
    private static int remaining(long deadline) throws SocketTimeoutException {
        long ms = (deadline - System.nanoTime()) / 1_000_000;
        if (ms <= 0) throw new SocketTimeoutException();
        return (int)Math.min(ms, Integer.MAX_VALUE);
    }
    private static String random() { byte[] bytes = new byte[32]; RANDOM.nextBytes(bytes); return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes); }
    private static Map<String,List<String>> formLists(String raw) {
        Map<String,List<String>> values = new LinkedHashMap<>();
        if (raw != null && !raw.isEmpty()) for (String part : raw.split("&")) {
            if (part.isEmpty()) continue;
            String[] pair = part.split("=", 2);
            String key = URLDecoder.decode(pair[0], StandardCharsets.UTF_8);
            String v = URLDecoder.decode(pair.length == 2 ? pair[1] : "", StandardCharsets.UTF_8);
            values.computeIfAbsent(key, ignored -> new ArrayList<>()).add(v);
        }
        return values;
    }
    private static Map<String,String> form(String raw) {
        Map<String,String> result = new LinkedHashMap<>();
        formLists(raw).forEach((k, v) -> result.put(k, v.getLast())); return result;
    }
    private static String encode(Map<String,String> values) {
        List<String> parts = new ArrayList<>();
        values.forEach((k,v) -> parts.add(URLEncoder.encode(k, StandardCharsets.UTF_8) + "=" + URLEncoder.encode(v, StandardCharsets.UTF_8)));
        return String.join("&", parts);
    }

    /** Bounded JSON reader for presets and token responses; no reflection, no dependencies. */
    private static final class Json {
        private final String text; private int pos;
        private Json(String text) { this.text = text; }
        @SuppressWarnings("unchecked") static Map<String,Object> object(String text) {
            Json parser = new Json(text); Object result = parser.read(0); parser.space();
            if (!(result instanceof Map<?,?>) || parser.pos != text.length()) throw new IllegalArgumentException();
            return (Map<String,Object>) result;
        }
        private void space() { while (pos < text.length() && " \r\n\t".indexOf(text.charAt(pos)) >= 0) pos++; }
        private char next() { if (pos >= text.length()) throw new IllegalArgumentException(); return text.charAt(pos++); }
        private boolean take(char c) { space(); if (pos < text.length() && text.charAt(pos) == c) { pos++; return true; } return false; }
        private Object read(int depth) {
            if (depth > 32) throw new IllegalArgumentException(); space();
            if (take('{')) {
                Map<String,Object> map = new LinkedHashMap<>(); if (take('}')) return map;
                do { space(); String key = string(); if (!take(':')) throw new IllegalArgumentException(); map.put(key, read(depth + 1)); } while (take(','));
                if (!take('}')) throw new IllegalArgumentException(); return map;
            }
            if (take('[')) {
                List<Object> list = new ArrayList<>(); if (take(']')) return list;
                do { list.add(read(depth + 1)); } while (take(','));
                if (!take(']')) throw new IllegalArgumentException(); return list;
            }
            if (pos < text.length() && text.charAt(pos) == '"') return string();
            for (String word : List.of("true", "false", "null")) if (text.startsWith(word, pos)) { pos += word.length(); return word.equals("null") ? null : word.equals("true"); }
            int start = pos; while (pos < text.length() && "-+0123456789.eE".indexOf(text.charAt(pos)) >= 0) pos++;
            String number = text.substring(start, pos);
            if (!number.matches("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")) throw new IllegalArgumentException();
            return Double.valueOf(number);
        }
        private String string() {
            if (next() != '"') throw new IllegalArgumentException(); StringBuilder out = new StringBuilder();
            while (true) {
                char c = next(); if (c == '"') return out.toString(); if (c < 32) throw new IllegalArgumentException();
                if (c == '\\') {
                    c = next();
                    switch (c) {
                        case '"', '\\', '/' -> out.append(c);
                        case 'b' -> out.append('\b'); case 'f' -> out.append('\f'); case 'n' -> out.append('\n'); case 'r' -> out.append('\r'); case 't' -> out.append('\t');
                        case 'u' -> { if (pos + 4 > text.length()) throw new IllegalArgumentException(); out.append((char)Integer.parseInt(text.substring(pos, pos + 4),16)); pos += 4; }
                        default -> throw new IllegalArgumentException();
                    }
                } else out.append(c);
            }
        }
    }
}
