package ai.lmctl.lmclient.areas;

import ai.lmctl.lmclient.core.Env;
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.TopicPartition;
import java.net.URI;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Plaintext Kafka: partition-zero produce and bounded, earliest-offset reads. */
public final class KafkaArea {
    private KafkaArea() {}
    public static int run(String[] args) {
        Map<String,String> options = new HashMap<>();
        String command, url;
        int timeout, limit;
        try {
            if (args.length == 0) throw new IllegalArgumentException();
            command = args[0];
            Set<String> allowed = new HashSet<>(Set.of("--url", "--timeout"));
            switch (command) {
                case "produce" -> allowed.addAll(Set.of("--topic", "--message"));
                case "consume" -> allowed.addAll(Set.of("--topic", "--limit"));
                case "ping" -> { }
                default -> throw new IllegalArgumentException();
            }
            for (int i = 1; i < args.length; i += 2) {
                if (!allowed.contains(args[i]) || i + 1 >= args.length || options.putIfAbsent(args[i], args[i+1]) != null)
                    throw new IllegalArgumentException();
            }
            timeout = positive(options.getOrDefault("--timeout", "10000"), Integer.MAX_VALUE);
            limit = positive(options.getOrDefault("--limit", "1"), 10000);
            url = options.getOrDefault("--url", Env.get("LMCLIENT_KAFKA_URL"));
            URI endpoint = new URI("tcp://" + (url == null ? "" : url));
            if (endpoint.getHost() == null || endpoint.getPort() < 1 || endpoint.getPort() > 65535
                    || endpoint.getUserInfo() != null || endpoint.getQuery() != null || endpoint.getFragment() != null
                    || !endpoint.getPath().isEmpty()) throw new IllegalArgumentException();
            String topic = options.getOrDefault("--topic", "");
            if (!command.equals("ping") && (!topic.matches("[a-zA-Z0-9._-]{1,249}") || topic.equals(".") || topic.equals("..")))
                throw new IllegalArgumentException();
            if (command.equals("produce") && !options.containsKey("--message")) throw new IllegalArgumentException();
        } catch (Exception e) {
            return Envelope.fail("USAGE", "kafka produce|consume|ping: use --url host:port (or LMCLIENT_KAFKA_URL), --topic and --message for produce, --limit for consume; --timeout must be positive milliseconds");
        }
        Properties config = new Properties();
        config.put("bootstrap.servers", url);
        config.put("request.timeout.ms", Integer.toString(timeout));
        config.put("socket.connection.setup.timeout.ms", Integer.toString(timeout));
        config.put("socket.connection.setup.timeout.max.ms", Integer.toString(timeout));
        KafkaProducer<String,String> producer = null;
        KafkaConsumer<String,String> consumer = null;
        try {
            long deadline = System.nanoTime() + timeout * 1_000_000L;
            if (command.equals("produce")) {
                config.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
                config.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
                config.put("max.block.ms", Integer.toString(timeout));
                config.put("delivery.timeout.ms", Integer.toString(timeout));
                config.put("linger.ms", "0");
                config.put("acks", "all");
                producer = new KafkaProducer<>(config);
                // A fixed partition preserves ordering across separate CLI invocations.
                producer.send(new ProducerRecord<>(options.get("--topic"), 0, null, options.get("--message")))
                        .get(remaining(deadline).toNanos(), TimeUnit.NANOSECONDS);
                return Envelope.ok("{\"published\":true}");
            }
            config.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
            config.put("value.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
            config.put("enable.auto.commit", "false");
            config.put("auto.offset.reset", "earliest");
            config.put("default.api.timeout.ms", Integer.toString(timeout));
            consumer = new KafkaConsumer<>(config);
            if (command.equals("ping")) {
                consumer.listTopics(remaining(deadline));
                return Envelope.ok("{\"connected\":true}");
            }
            String topic = options.get("--topic");
            List<TopicPartition> partitions = consumer.partitionsFor(topic, remaining(deadline)).stream()
                    .map(p -> new TopicPartition(topic, p.partition())).toList();
            if (partitions.isEmpty()) throw new IllegalStateException();
            consumer.assign(partitions);
            consumer.seekToBeginning(partitions);
            List<String> messages = new ArrayList<>();
            while (messages.size() < limit && System.nanoTime() < deadline) {
                for (ConsumerRecord<String,String> record : consumer.poll(remaining(deadline))) {
                    messages.add(record.value() == null ? "null" : Envelope.quote(record.value()));
                    if (messages.size() == limit) break;
                }
            }
            return Envelope.ok("{\"messages\":[" + String.join(",", messages) + "]}");
        } catch (Exception e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
            return Envelope.fail("CONN", "Kafka operation failed; check broker, topic permissions, and timeout");
        } finally {
            if (producer != null) try { producer.close(Duration.ZERO); } catch (Exception ignored) { }
            if (consumer != null) try { consumer.close(Duration.ZERO); } catch (Exception ignored) { }
        }
    }
    private static Duration remaining(long deadline) { return Duration.ofNanos(Math.max(0, deadline - System.nanoTime())); }
    private static int positive(String value, int max) {
        int n = Integer.parseInt(value);
        if (n < 1 || n > max) throw new IllegalArgumentException();
        return n;
    }
}
