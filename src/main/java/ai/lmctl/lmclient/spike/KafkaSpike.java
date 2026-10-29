package ai.lmctl.lmclient.spike;

import ai.lmctl.lmclient.areas.Envelope;
import org.apache.kafka.clients.consumer.*;
import org.apache.kafka.clients.producer.*;
import org.apache.kafka.common.TopicPartition;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.TimeUnit;

/** Branch-only reachability and live round-trip probe, not part of the area registry. */
public final class KafkaSpike {
    public static void main(String[] args) {
        try {
            boolean construct = args.length == 1 && args[0].equals("--construct");
            if (!construct && args.length != 1) {
                System.exit(Envelope.fail("USAGE", "KafkaSpike HOST:PORT | --construct"));
            }
            String broker = construct ? "127.0.0.1:1" : args[0];
            Properties p = new Properties();
            p.put("bootstrap.servers", broker);
            // Class names deliberately exercise Kafka's configured-class reflection path.
            p.put("key.serializer", "org.apache.kafka.common.serialization.StringSerializer");
            p.put("value.serializer", "org.apache.kafka.common.serialization.StringSerializer");
            p.put("max.block.ms", "10000"); p.put("request.timeout.ms", "5000");
            p.put("delivery.timeout.ms", "15000"); p.put("acks", "all");
            Properties c = new Properties();
            c.put("bootstrap.servers", broker);
            c.put("key.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
            c.put("value.deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
            c.put("group.id", "lmclient-spike-" + UUID.randomUUID());
            c.put("enable.auto.commit", "false"); c.put("auto.offset.reset", "earliest");
            c.put("default.api.timeout.ms", "10000"); c.put("request.timeout.ms", "5000");
            try (KafkaProducer<String,String> producer = new KafkaProducer<>(p);
                 KafkaConsumer<String,String> consumer = new KafkaConsumer<>(c)) {
                if (construct) { Envelope.ok("{\"constructed\":true}"); return; }
                String topic = "lmclient-spike-" + UUID.randomUUID();
                String payload = "hello Kafka — UTF-8";
                RecordMetadata sent = producer.send(new ProducerRecord<>(topic, "key", payload)).get(20, TimeUnit.SECONDS);
                TopicPartition partition = new TopicPartition(topic, sent.partition());
                consumer.assign(List.of(partition)); consumer.seek(partition, sent.offset());
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(20);
                while (System.nanoTime() < deadline) {
                    for (ConsumerRecord<String,String> record : consumer.poll(Duration.ofMillis(500))) {
                        if (record.offset() == sent.offset() && "key".equals(record.key()) && payload.equals(record.value())) {
                            Envelope.ok("{\"roundTrip\":true,\"topic\":" + Envelope.quote(topic) + ",\"payload\":" + Envelope.quote(record.value()) + "}");
                            return;
                        }
                    }
                }
                throw new IllegalStateException("round-trip deadline exceeded");
            }
        } catch (Throwable e) {
            // Only dummy local endpoints/values are used by this spike. Keep exact errors for native diagnostics.
            e.printStackTrace(System.err);
            System.exit(Envelope.fail("SPIKE_FAILED", e.getClass().getName()));
        }
    }
}
