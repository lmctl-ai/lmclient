package ai.lmctl.lmclient.areas;

/**
 * queue area — replaces n8n's RabbitMQ and AMQP nodes.
 * PINNED CLI contract (wave 5b; owner Astra3; details docs/areas/queue.md):
 *   lmclient queue publish --url amqp://[user:pass@]host[:5672]/ --queue Q --body TEXT
 *   lmclient queue consume --url ... --queue Q --limit N --timeout MS
 *   lmclient queue ping --url ...
 * LMCLIENT_QUEUE_URL env fallback. Envelope per Envelope.java; error codes CONN / USAGE.
 * Client: com.rabbitmq:amqp-client.
 */
public final class QueueArea {
    private QueueArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "queue area not implemented yet"); }
}
