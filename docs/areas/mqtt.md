# MQTT

`lmclient mqtt pub --url tcp://localhost:1883 --topic demo --message hello --qos 1`
publishes a UTF-8 message. `mqtt sub --topic demo --limit 3 --timeout 10000`
subscribes and returns `{"messages":[{"topic":"demo","payload":"hello"},...]}`.
Subscriptions must be active before publishing; messages are not retained.
A timeout returns the messages collected, including an empty list. `mqtt ping`
connects to the broker. QoS 0, 1, and 2 are supported; default is 0.

Connection URL: `--url` or `LMCLIENT_MQTT_URL`. Use `tcp://` or `ssl://`.
Authentication uses `LMCLIENT_USER`/`LMCLIENT_PASSWORD` or `--credentials-file`
with `user` and `password` properties; environment values override the file.
All commands accept `--timeout` in milliseconds (default 10000). Limits must
be 1..10000. Errors are sanitized `CONN` (exit 3) or `USAGE` (exit 2).
Each invocation uses a unique client ID and an in-memory, clean session.
There is no persistent-session, retained-publication, or MQTT 5 API.

## wiring

- Maven: `org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5`.
- Test: `python3 scripts/test-mqtt.py target/lmclient-0.2.0-all.jar` (also accepts a native executable).
- CI service: `eclipse-mosquitto:2`, TCP 1883, config `listener 1883` and `allow_anonymous true`; the test starts and removes its own container with a random loopback host port.
- Native: Paho uses socket network modules and in-memory persistence. Retain its ServiceLoader providers via the existing shaded services transformer. Area native-image metadata registers its reflective logger and message resource bundles. Native verification belongs to CI; local verification is JVM only.
- Example: `lmscript examples/mqtt_demo.lms` (service must be running; skips if unreachable).
