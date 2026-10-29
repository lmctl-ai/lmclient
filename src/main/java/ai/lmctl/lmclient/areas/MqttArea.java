package ai.lmctl.lmclient.areas;

/**
 * mqtt area — replaces n8n's MQTT node.
 * PINNED CLI contract (wave 5b; owner Astra3; details docs/areas/mqtt.md):
 *   lmclient mqtt pub --url tcp://host:1883 --topic T --message M [--qos 0|1|2]
 *   lmclient mqtt sub --url tcp://host:1883 --topic T --limit N --timeout MS
 *   lmclient mqtt ping --url ...
 * LMCLIENT_MQTT_URL env fallback. Envelope per Envelope.java.
 * Client: org.eclipse.paho.client.mqttv3.
 */
public final class MqttArea {
    private MqttArea() {}
    public static int run(String[] args) { return Envelope.fail("USAGE", "mqtt area not implemented yet"); }
}
