# AMQP queues

`lmclient queue publish --url amqp://localhost:5672/ --queue jobs --body hello`
declares a durable queue and publishes a persistent UTF-8 message with publisher
confirmation. `queue consume --queue jobs --limit 3 --timeout 10000` reads
up to three messages in broker order, automatically acknowledging each read.
It returns `{"messages":["hello",...]}`; a timeout returns the messages collected,
including an empty list. Consumption is destructive; there is no manual ack/requeue API.
`queue ping` opens a connection and channel.

Connection URL: `--url` or `LMCLIENT_QUEUE_URL`. Authentication comes from URL
userinfo, or `LMCLIENT_USER`/`LMCLIENT_PASSWORD`, or `--credentials-file` with
`user` and `password` properties. Environment values override file values;
explicit credential fields override URL credentials. Do not put real passwords
in shell history. Errors are sanitized `CONN` (exit 3) or `USAGE` (exit 2).
All commands accept `--timeout` in milliseconds (default 10000). Limits must
be 1..10000. Only AMQP 0-9-1 is supported, not AMQP 1.0.

## wiring

- Maven: `com.rabbitmq:amqp-client:5.22.0`.
- Test: `python3 scripts/test-queue.py target/lmclient-0.2.0-all.jar` (also accepts a native executable).
- CI service: `rabbitmq:3-alpine`, TCP 5672, guest/guest; the test starts and removes its own container with a random loopback host port.
- Native: plain socket RabbitMQ client, no Netty or dynamic proxies. No application reflection configuration needed. Native verification belongs to CI; local verification is JVM only.
- Example: `lmscript examples/queue_demo.lms` (service must be running; skips if unreachable).
