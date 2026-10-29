package ai.lmctl.lmclient.areas;

import java.util.Map;

/**
 * Protocol-area registry. Explicit references only — no reflection and no
 * ServiceLoader scan, so GraalVM native-image sees every area class.
 * Each area class has `public static int run(String[] args)`.
 */
public final class Areas {
    private Areas() {}

    public interface AreaMain {
        int run(String[] args) throws Exception;
    }

    public static final Map<String, AreaMain> REGISTRY = Map.of(
        "redis", RedisArea::run,
        "mail", MailArea::run,
        "queue", QueueArea::run,
        "mqtt", MqttArea::run,
        "mongo", MongoArea::run
    );
}
