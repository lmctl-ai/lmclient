package ai.lmctl.lmclient.areas;

/**
 * redis area — replaces n8n's Redis node (key/value, lists, publish).
 * PINNED CLI contract (wave 5b; owner Astra1; details docs/areas/redis.md):
 *   lmclient redis ping
 *   lmclient redis get KEY
 *   lmclient redis set KEY VALUE [--ttl SECONDS]
 *   lmclient redis del KEY [KEY...]
 *   lmclient redis lpush KEY VALUE [VALUE...]
 *   lmclient redis rpop KEY
 *   lmclient redis lrange KEY START STOP
 *   lmclient redis publish CHANNEL MESSAGE
 * Connection: --url redis://[:password@]host[:port][/db] or LMCLIENT_REDIS_URL.
 * Envelope per Envelope.java; error codes CONN / USAGE. Client: jedis.
 */
public final class RedisArea {
    private RedisArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "redis area not implemented yet"); }
}
