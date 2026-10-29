package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.Credentials;
import ai.lmctl.lmclient.core.Env;
import com.rabbitmq.client.*;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;

/** AMQP 0-9-1: durable publish, bounded auto-ack consume, and ping. */
public final class QueueArea {
    private QueueArea() {}
    public static int run(String[] args) {
        Map<String, String> options = new HashMap<>();
        String command;
        int timeout, limit;
        URI uri;
        try {
            if (args.length == 0) throw new IllegalArgumentException();
            command = args[0];
            Set<String> allowed = new HashSet<>(Set.of("--url", "--credentials-file", "--timeout"));
            switch (command) {
                case "publish" -> allowed.addAll(Set.of("--queue", "--body"));
                case "consume" -> allowed.addAll(Set.of("--queue", "--limit"));
                case "ping" -> { }
                default -> throw new IllegalArgumentException();
            }
            for (int i = 1; i < args.length; i += 2) {
                if (!allowed.contains(args[i]) || i + 1 >= args.length || options.putIfAbsent(args[i], args[i + 1]) != null)
                    throw new IllegalArgumentException();
            }
            timeout = positive(options.getOrDefault("--timeout", "10000"), Integer.MAX_VALUE);
            limit = positive(options.getOrDefault("--limit", "1"), 10000);
            String url = options.getOrDefault("--url", Env.get("LMCLIENT_QUEUE_URL"));
            uri = new URI(url == null ? "" : url);
            if (!Set.of("amqp", "amqps").contains(uri.getScheme() == null ? "" : uri.getScheme()) || uri.getHost() == null
                    || uri.getPort() > 65535 || uri.getFragment() != null || uri.getQuery() != null) throw new IllegalArgumentException();
            if (!command.equals("ping") && (options.getOrDefault("--queue", "").isBlank()
                    || options.get("--queue").getBytes(StandardCharsets.UTF_8).length > 255)) throw new IllegalArgumentException();
            if (command.equals("publish") && !options.containsKey("--body")) throw new IllegalArgumentException();
        } catch (Exception e) {
            return Envelope.fail("USAGE", "queue publish|consume|ping: use --url (or LMCLIENT_QUEUE_URL), --queue and --body for publish, --limit for consume; --timeout must be positive milliseconds");
        }
        Connection connection = null;
        try {
            Properties credentials = Credentials.read(options.get("--credentials-file"));
            ConnectionFactory factory = new ConnectionFactory();
            factory.setUri(uri);
            // The CLI contract uses a trailing slash for RabbitMQ's default vhost.
            if ("/".equals(uri.getRawPath())) factory.setVirtualHost("/");
            if (credentials.containsKey("user")) factory.setUsername(credentials.getProperty("user"));
            if (credentials.containsKey("password")) factory.setPassword(credentials.getProperty("password"));
            factory.setConnectionTimeout(timeout);
            factory.setHandshakeTimeout(timeout);
            factory.setChannelRpcTimeout(timeout);
            factory.setShutdownTimeout(timeout);
            factory.setAutomaticRecoveryEnabled(false);
            factory.setTopologyRecoveryEnabled(false);
            // Do not let background driver diagnostics print credential-bearing exceptions.
            factory.setExceptionHandler(new com.rabbitmq.client.impl.DefaultExceptionHandler() {
                @Override protected void log(String message, Throwable error) { }
            });
            connection = factory.newConnection();
            Channel channel = connection.createChannel();
            if (command.equals("ping")) return Envelope.ok("{\"connected\":true}");
            String queue = options.get("--queue");
            channel.queueDeclare(queue, true, false, false, null);
            if (command.equals("publish")) {
                channel.confirmSelect();
                channel.basicPublish("", queue, MessageProperties.PERSISTENT_TEXT_PLAIN,
                        options.get("--body").getBytes(StandardCharsets.UTF_8));
                channel.waitForConfirmsOrDie(timeout);
                return Envelope.ok("{\"published\":true}");
            }
            long deadline = System.nanoTime() + timeout * 1_000_000L;
            List<String> messages = new ArrayList<>();
            while (messages.size() < limit && System.nanoTime() < deadline) {
                GetResponse response = channel.basicGet(queue, true);
                if (response == null) {
                    long remaining = (deadline - System.nanoTime()) / 1_000_000;
                    if (remaining > 0) Thread.sleep(Math.min(50, remaining));
                } else messages.add(Envelope.quote(new String(response.getBody(), StandardCharsets.UTF_8)));
            }
            return Envelope.ok("{\"messages\":[" + String.join(",", messages) + "]}");
        } catch (Exception e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            return Envelope.fail("CONN", "AMQP operation failed; check connection, credentials, queue settings, and timeout");
        } finally {
            if (connection != null) try { connection.abort(timeout); } catch (Exception ignored) { }
        }
    }
    private static int positive(String value, int max) {
        int n = Integer.parseInt(value);
        if (n < 1 || n > max) throw new IllegalArgumentException();
        return n;
    }
}
