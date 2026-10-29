package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.Credentials;
import ai.lmctl.lmclient.core.Env;
import org.eclipse.paho.client.mqttv3.*;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/** MQTT 3.1.1: pub/sub/ping with clean sessions and bounded operations. */
public final class MqttArea {
    private MqttArea() {}
    public static int run(String[] args) {
        Map<String, String> options = new HashMap<>();
        String command, url;
        int timeout, limit, qos;
        try {
            if (args.length == 0) throw new IllegalArgumentException();
            command = args[0];
            Set<String> allowed = new HashSet<>(Set.of("--url", "--credentials-file", "--timeout"));
            switch (command) {
                case "pub" -> allowed.addAll(Set.of("--topic", "--message", "--qos"));
                case "sub" -> allowed.addAll(Set.of("--topic", "--limit", "--qos"));
                case "ping" -> { }
                default -> throw new IllegalArgumentException();
            }
            for (int i = 1; i < args.length; i += 2) {
                if (!allowed.contains(args[i]) || i + 1 >= args.length || options.putIfAbsent(args[i], args[i + 1]) != null)
                    throw new IllegalArgumentException();
            }
            timeout = positive(options.getOrDefault("--timeout", "10000"), Integer.MAX_VALUE);
            limit = positive(options.getOrDefault("--limit", "1"), 10000);
            qos = Integer.parseInt(options.getOrDefault("--qos", "0"));
            if (qos < 0 || qos > 2) throw new IllegalArgumentException();
            url = options.getOrDefault("--url", Env.get("LMCLIENT_MQTT_URL"));
            URI uri = new URI(url == null ? "" : url);
            if (!Set.of("tcp", "ssl").contains(uri.getScheme() == null ? "" : uri.getScheme()) || uri.getHost() == null
                    || uri.getPort() > 65535 || uri.getUserInfo() != null || uri.getQuery() != null || uri.getFragment() != null
                    || !(uri.getPath() == null || uri.getPath().isEmpty())) throw new IllegalArgumentException();
            if (!command.equals("ping")) MqttTopic.validate(options.getOrDefault("--topic", ""), command.equals("sub"));
            if (command.equals("pub") && !options.containsKey("--message")) throw new IllegalArgumentException();
        } catch (Exception e) {
            return Envelope.fail("USAGE", "mqtt pub|sub|ping: use --url (or LMCLIENT_MQTT_URL), --topic and --message for pub, --limit for sub; --qos is 0..2 and --timeout is positive milliseconds");
        }
        MqttAsyncClient client = null;
        try {
            Properties credentials = Credentials.read(options.get("--credentials-file"));
            MqttConnectOptions connect = new MqttConnectOptions();
            connect.setMqttVersion(MqttConnectOptions.MQTT_VERSION_3_1_1);
            connect.setCleanSession(true);
            connect.setAutomaticReconnect(false);
            connect.setConnectionTimeout((int) Math.max(1, (timeout + 999L) / 1000));
            if (credentials.containsKey("user")) connect.setUserName(credentials.getProperty("user"));
            if (credentials.containsKey("password")) connect.setPassword(credentials.getProperty("password").toCharArray());
            client = new MqttAsyncClient(url, "lmclient-" + UUID.randomUUID(), new MemoryPersistence());
            BlockingQueue<String> received = new ArrayBlockingQueue<>(limit);
            AtomicBoolean lost = new AtomicBoolean();
            client.setCallback(new MqttCallback() {
                public void connectionLost(Throwable cause) { lost.set(true); }
                public void deliveryComplete(IMqttDeliveryToken token) { }
                public void messageArrived(String topic, MqttMessage message) {
                    received.offer("{\"topic\":" + Envelope.quote(topic) + ",\"payload\":"
                            + Envelope.quote(new String(message.getPayload(), StandardCharsets.UTF_8)) + "}");
                }
            });
            client.connect(connect).waitForCompletion(timeout);
            if (command.equals("ping")) return Envelope.ok("{\"connected\":true}");
            if (command.equals("pub")) {
                client.publish(options.get("--topic"), options.get("--message").getBytes(StandardCharsets.UTF_8), qos, false).waitForCompletion(timeout);
                return Envelope.ok("{\"published\":true}");
            }
            IMqttToken subscribed = client.subscribe(options.get("--topic"), qos);
            subscribed.waitForCompletion(timeout);
            if (subscribed.getGrantedQos()[0] == 128) throw new MqttException(MqttException.REASON_CODE_SUBSCRIBE_FAILED);
            long deadline = System.nanoTime() + timeout * 1_000_000L;
            List<String> messages = new ArrayList<>();
            while (messages.size() < limit && System.nanoTime() < deadline) {
                if (lost.get()) throw new MqttException(MqttException.REASON_CODE_CONNECTION_LOST);
                long remaining = deadline - System.nanoTime();
                String message = received.poll(Math.max(1, Math.min(remaining, 100_000_000L)), TimeUnit.NANOSECONDS);
                if (message != null) messages.add(message);
            }
            return Envelope.ok("{\"messages\":[" + String.join(",", messages) + "]}");
        } catch (Exception e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            return Envelope.fail("CONN", "MQTT operation failed; check connection, credentials, topic permissions, and timeout");
        } finally {
            if (client != null) {
                try { client.disconnectForcibly(0, 0, false); } catch (Exception ignored) { }
                try { client.close(true); } catch (Exception ignored) { }
            }
        }
    }
    private static int positive(String value, int max) {
        int n = Integer.parseInt(value);
        if (n < 1 || n > max) throw new IllegalArgumentException();
        return n;
    }
}
