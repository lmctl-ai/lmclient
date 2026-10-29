# Kafka native-image spike

Branch-only experiment: `spike/kafka`. No Kafka area is registered and this
branch is not intended to merge unchanged into main.

## wiring

- Dependency: `org.apache.kafka:kafka-clients:3.9.1` (branch POM only).
- Entry point: `ai.lmctl.lmclient.spike.KafkaSpike`.
- JVM build: `mvn -q -B package -DskipTests`.
- JVM live gate: `python3 scripts/test-kafka-spike.py target/lmclient-0.2.0-all.jar`.
- Native gate: `python3 scripts/test-kafka-spike.py target/kafka-spike`.
- Broker: `apache/kafka:3.9.1`, default single-node KRaft, port 9092.
  The script starts `lmclient-kafka` and always removes it.
- CI: dispatch `ci.yml` on `spike/kafka`. Branch-only jobs build a native
  executable with **KafkaSpike as the entry point**, ensuring producer and
  consumer code is reachable. Merely adding Kafka to the normal unused
  classpath would not test native compatibility.
- Five native targets: Linux x64/arm64, macOS x64/arm64, Windows x64.
  All construct a real producer and consumer; Linux also performs the live
  produce/consume round-trip. Other normal CI jobs are skipped only on this
  spike branch, avoiding unrelated JDBC engine-build gates.
- Initial native command: `native-image --no-fallback -J-Xmx4g
  -H:NumberOfThreads=2 -cp target/lmclient-0.2.0-all.jar
  ai.lmctl.lmclient.spike.KafkaSpike target/kafka-spike`.

The test uses configured serializer/deserializer **class names**, default Kafka
metrics behavior, a unique topic/group, explicit delivery/API deadlines,
and UTF-8 payload comparison. It uses no credentials. TLS/SASL, alternate
partition assignors, interceptors, compression, transactions, and production
broker failover are outside this small gate.

## Verdict

JVM live round-trip passed against `apache/kafka:3.9.1` (UTF-8 key/payload
and offset verified; container removed). Native result is pending.

The first CI dispatch (40822836520) failed before Kafka analysis with an
unrelated family-jar feature error:

```
Error: User-enabled Feature org.sqlite.nativeimage.SqliteJdbcFeature class not found.
```

The spike harness now builds a Kafka-only classpath (the two spike classes,
Kafka, SLF4J, and Kafka compression dependencies), excluding unrelated JDBC
metadata. This corrects the experiment; it is not a Kafka reflection fix.
No native build is run locally.
