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
- Mock tier (all platforms): `scripts/lmmock-helpers.py` locates `LMMOCK_BIN`,
  then `lmmock` on PATH, or downloads the checksum-verified pinned release
  (v0.1.13 or newer, including `amqp`). It starts `lmmock proto amqp` on an
  ephemeral loopback port with a temporary JSON config
  `{"users":{"guest":"guest"}}`, and always stops the process and removes its
  temporary files. The readiness URL gets guest/guest userinfo and `/` for the
  default virtual host. The credentials-file check removes URL userinfo.
- The same endpoint-injected live assertions run against lmmock first and
  RabbitMQ second: confirmed persistent publishes, FIFO destructive `basic.get`,
  empty polling, environment URL, credentials-file success and bad-password
  rejection. Usage/connection-error checks run once before either backend.
  All 18 original checks remain; 8 live checks repeat against Docker, for 26 total.
- Docker tier: `rabbitmq:3-alpine`, TCP 5672, guest/guest; the test starts and
  removes its own container with an ephemeral loopback host port. Missing Docker,
  Windows-container daemons, and infrastructure startup failures skip only this
  tier, after the mock checks have completed.
- Local lmmock acquisition failure prints SKIP and exits 0; `LMMOCK_REQUIRED=1`
  makes it fail instead (the CI setting). A running mock's assertion failures
  always fail. To exercise local skip handling:
  `LMMOCK_BIN=/nonexistent/lmmock python3 scripts/test-queue.py`.
- The mock accepts durable/persistent flags but stores only in memory. There
  are currently no restart-durability, TLS, non-default-exchange, or consumer
  subscription assertions to exclude. Future checks for those features must
  remain Docker-only; none of the existing assertions were weakened.
- Native: plain socket RabbitMQ client, no Netty or dynamic proxies. No application reflection configuration needed. Native verification belongs to CI; local verification is JVM only.
- Example: `lmscript examples/queue_demo.lms` (service must be running; skips if unreachable).

## verification

JVM suite: 18 checks passed through the released lmmock tier (10 shared checks
and 8 live), then 8 live checks passed against RabbitMQ: 26 total.
RabbitMQ: published three messages, consumed the same three in order, then verified the queue was empty. Credentials-file authentication and secret-safe failures passed.
The isolated JVM `mvn -q -B package -DskipTests` build passed. Forced local
lmmock-unavailable and Docker-absent runs exited 0 with explicit SKIP messages;
the Docker-absent run still completed all 18 mock-backed checks. Native-image and TLS
interoperability have not been tested locally.
