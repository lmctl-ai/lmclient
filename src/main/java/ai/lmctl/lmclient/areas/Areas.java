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
        "kafka", KafkaArea::run,
        "mqtt", MqttArea::run,
        "mongo", MongoArea::run
    );

    /** Wave 6 areas (lmconn ports) — registered separately so wave-5b merges stay trivial. */
    public static final Map<String, AreaMain> WAVE6 = Map.of(
        "cred", CredArea::run,
        "http", HttpArea::run,
        "oauth", OauthArea::run,
        "llm", LlmArea::run,
        "github", GithubArea::run
    );

    public static AreaMain lookup(String name) {
        AreaMain area = REGISTRY.get(name);
        return area != null ? area : WAVE6.get(name);
    }
}
