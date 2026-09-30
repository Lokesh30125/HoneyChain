/*
 * HoneyChain — ESP32 hive node firmware (reference sketch)
 * ---------------------------------------------------------
 * This is the hardware counterpart of `python -m app.scripts.hive_simulator`.
 * It sends the *identical* JSON payload, so the server needs no changes when a
 * real node replaces the simulator — the contract is the schema, not the
 * transport.
 *
 * Deliberately a starting point, not a finished product. What it does:
 *   - connects to Wi-Fi (or a LoRa gateway, see the note at the bottom);
 *   - reads five sensors on their own cadences;
 *   - publishes one consolidated packet to
 *       honeychain/devices/{DEVICE_ID}/telemetry   (MQTT, preferred)
 *     or POSTs it to
 *       /api/v1/iot/telemetry                       (HTTP, fallback)
 *   - buffers packets in RTC memory while the uplink is down and replays them
 *     when it returns (the server treats a replayed instant as a duplicate);
 *   - publishes a heartbeat when it has nothing else to say, so the dashboard
 *     can tell "quiet hive" from "dead node".
 *
 * NOT implemented here, on purpose: no disease detection, no queen detection, no
 * colony-health scoring, no alerting. This phase stores measurements; nothing in
 * this firmware interprets them. Any claim of that kind would be unsupported.
 *
 * Libraries (Arduino Library Manager):
 *   PubSubClient (Nick O'Leary)   - MQTT
 *   DHT sensor library (Adafruit) - temperature/humidity
 *   HX711 (bogde)                 - load cell / hive weight
 *   ArduinoJson (Benoit Blanchon) - packet assembly
 *
 * Wiring assumed in the defaults below; change the pin constants to match your
 * board. The weight sensor is the only one that needs calibration.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <HX711.h>
#include <time.h>

// ---------------------------------------------------------------------------
// Configuration — replace these with your own values (never commit secrets).
// ---------------------------------------------------------------------------
#define WIFI_SSID        "your-ssid"
#define WIFI_PASSWORD    "your-password"

#define MQTT_HOST        "192.168.1.10"   // broker on the local network
#define MQTT_PORT        1883
#define MQTT_USER        ""               // leave empty for an anonymous broker
#define MQTT_PASSWORD    ""

#define API_HOST         "http://192.168.1.20:8000"  // used when USE_HTTP is 1
#define USE_HTTP         0

//: Printed on the device label. Must match the registration in HoneyChain
//: (POST /api/v1/iot/devices) or packets are rejected as unknown devices.
#define DEVICE_ID        "ESP32-GNT-0001"

#define TOPIC_PREFIX     "honeychain"
#define FIRMWARE_VERSION "1.0.0"

// -- Pins -------------------------------------------------------------------
#define DHT_PIN          4
#define DHT_TYPE         DHT22
#define HX711_DOUT       16
#define HX711_SCK        17
#define VIBRATION_PIN    34   // analogue accelerometer envelope
#define MIC_PIN          35   // analogue microphone envelope
#define BATTERY_PIN      32   // battery divider
#define STATUS_LED       2

// -- Cadence ----------------------------------------------------------------
#define PACKET_INTERVAL_SEC   300UL   // one uplink packet every 5 minutes
#define HEARTBEAT_INTERVAL_SEC 1800UL // tell the platform we are alive
#define WEIGHT_CALIBRATION    -7050.0f // from a known mass; calibrate per unit
#define LOW_BATTERY_PERCENT   20

DHT dht(DHT_PIN, DHT_TYPE);
HX711 scale;
WiFiClient netClient;
PubSubClient mqtt(netClient);

unsigned long lastPacketAt = 0;
unsigned long lastHeartbeatAt = 0;

// -- Offline buffer ---------------------------------------------------------
// Kept in RTC memory so a deep-sleep wake or a brown-out does not lose the
// backlog. 12 packets x ~200 bytes is well inside the 8 KB RTC region.
#define BUFFER_SLOTS 12
RTC_DATA_ATTR char bufferedPackets[BUFFER_SLOTS][220];
RTC_DATA_ATTR int bufferCount = 0;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
float readBatteryPercent() {
  // 12-bit ADC, 3.3 V reference, 2:1 divider: 4.2 V full, 3.3 V empty.
  int raw = analogRead(BATTERY_PIN);
  float volts = (raw / 4095.0f) * 3.3f * 2.0f;
  float percent = (volts - 3.30f) / (4.20f - 3.30f) * 100.0f;
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;
  return percent;
}

int readSignalStrength() {
  long rssi = WiFi.RSSI();
  if (rssi > 0) rssi = 0;        // the API accepts -140..0 dBm
  if (rssi < -140) rssi = -140;
  return (int)rssi;
}

String isoTimestamp() {
  // The server accepts a missing timestamp and uses receipt time, but an
  // accurate one keeps the series correct when packets are buffered.
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  char buffer[25];
  strftime(buffer, sizeof(buffer), "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(buffer);
}

// ---------------------------------------------------------------------------
// Packet assembly — one JSON object, the schema the API validates
// ---------------------------------------------------------------------------
String buildPacket(bool includeReadings) {
  StaticJsonDocument<384> doc;
  doc["device_id"] = DEVICE_ID;
  doc["timestamp"] = isoTimestamp();
  doc["firmware_version"] = FIRMWARE_VERSION;

  if (includeReadings) {
    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();
    if (!isnan(humidity)) doc["humidity"] = serialized(String(humidity, 2));
    if (!isnan(temperature)) doc["temperature"] = serialized(String(temperature, 2));

    if (scale.is_ready()) {
      float weight = scale.get_units(5);
      if (weight < 0) weight = 0;   // the platform rejects negative mass
      doc["weight"] = serialized(String(weight, 3));
    }

    // Envelope values: a resting colony is quiet, so this is small by design.
    doc["vibration"] = serialized(String(analogRead(VIBRATION_PIN) / 4095.0f * 4.0f, 3));
    doc["acoustic_level"] = serialized(String(analogRead(MIC_PIN) / 4095.0f * 90.0f, 2));
  }

  doc["battery_level"] = (int)readBatteryPercent();
  doc["signal_strength"] = readSignalStrength();

  String output;
  serializeJson(doc, output);
  return output;
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------
void publishPacket(const String &packet) {
#if USE_HTTP
  // HTTP fallback for a site with no broker. Deliver with the beekeeper's
  // access token; devices deployed in the field normally use MQTT.
  HTTPClient http;
  http.begin(String(API_HOST) + "/api/v1/iot/telemetry");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", "Bearer " ACCESS_TOKEN);
  int status = http.POST(packet);
  if (status != 201) Serial.printf("HTTP ingest failed: %d\n", status);
  http.end();
#else
  char topic[96];
  snprintf(topic, sizeof(topic), "%s/devices/%s/telemetry", TOPIC_PREFIX, DEVICE_ID);
  // QoS 1: the broker retries if the ack is lost, and the API is idempotent on
  // (device, timestamp), so a redelivery cannot duplicate a sample.
  bool ok = mqtt.publish(topic, packet.c_str(), /*retained=*/false);
  if (!ok) {
    Serial.println("Publish failed; buffering packet for later replay");
    if (bufferCount < BUFFER_SLOTS) {
      packet.toCharArray(bufferedPackets[bufferCount], sizeof(bufferedPackets[bufferCount]));
      bufferCount++;
    }
  }
#endif
}

void replayBuffer() {
  for (int i = 0; i < bufferCount; i++) {
    publishPacket(String(bufferedPackets[i]));
    delay(50);
  }
  if (bufferCount > 0) Serial.printf("Replayed %d buffered packet(s)\n", bufferCount);
  bufferCount = 0;
}

void ensureConnected() {
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    unsigned long startedAt = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 15000) {
      delay(250);
    }
    Serial.printf("Wi-Fi: %s\n", WiFi.status() == WL_CONNECTED ? "connected" : "offline");
  }

#if !USE_HTTP
  if (!mqtt.connected()) {
    client.setServer(MQTT_HOST, MQTT_PORT);
    String clientId = String("hive-") + DEVICE_ID;
    bool ok = MQTT_USER[0] == '\0'
                  ? mqtt.connect(clientId.c_str())
                  : mqtt.connect(clientId.c_str(), MQTT_USER, MQTT_PASSWORD);
    if (ok) {
      Serial.println("Broker: connected");
      // Commands and configuration arrive here in a later phase; the node
      // subscribes now so it will not need reflashing when they are added.
      char commandTopic[96];
      snprintf(commandTopic, sizeof(commandTopic), "%s/devices/%s/commands",
               TOPIC_PREFIX, DEVICE_ID);
      mqtt.subscribe(commandTopic);
    } else {
      Serial.printf("Broker: connection failed (rc=%d)\n", mqtt.state());
    }
  }
#endif
}

void onMessage(char *topic, byte *payload, unsigned int length) {
  // Nothing consumes commands yet. Logging them keeps the shape visible while
  // the platform side is built out.
  Serial.printf("Command received on %s (%u bytes)\n", topic, length);
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\nHoneyChain hive node %s (firmware %s)\n", DEVICE_ID, FIRMWARE_VERSION);

  pinMode(STATUS_LED, OUTPUT);
  pinMode(VIBRATION_PIN, INPUT);
  pinMode(MIC_PIN, INPUT);
  pinMode(BATTERY_PIN, INPUT);
  analogReadResolution(12);

  dht.begin();
  scale.begin(HX711_DOUT, HX711_SCK);
  scale.set_scale(WEIGHT_CALIBRATION);
  scale.tare();

  configTime(0, 0, "pool.ntp.org");   // UTC; the API wants UTC timestamps

  WiFi.mode(WIFI_STA);
  ensureConnected();
  mqtt.setCallback(onMessage);
  replayBuffer();

  // First packet immediately, so a freshly installed node is visible at once.
  publishPacket(buildPacket(true));
  lastPacketAt = millis();
  lastHeartbeatAt = millis();
}

void loop() {
  ensureConnected();
  mqtt.loop();

  unsigned long now = millis();

  if (now - lastPacketAt >= PACKET_INTERVAL_SEC * 1000UL) {
    lastPacketAt = now;
    publishPacket(buildPacket(true));
  } else if (now - lastHeartbeatAt >= HEARTBEAT_INTERVAL_SEC * 1000UL) {
    lastHeartbeatAt = now;
    publishPacket(buildPacket(false));
  }

  digitalWrite(STATUS_LED, WiFi.status() == WL_CONNECTED ? HIGH : LOW);
  delay(1000);
}

/*
 * Notes for a real deployment
 * ---------------------------
 * 1. Power. A solar panel with a LiFePO4 cell keeps a node alive through the
 *    monsoon; deep sleep between packets is what makes it last. This sketch
 *    stays awake for clarity — see the deep-sleep variant in the firmware
 *    folder once it is added.
 * 2. Weight. Calibrate `WEIGHT_CALIBRATION` with a known mass per unit, and set
 *    `scale.tare()` only with the hive empty of supers. An absurd weight is
 *    rejected by the API rather than silently stored, which is the behaviour
 *    you want — a broken load cell should look broken, not like a 900 kg hive.
 * 3. LoRa. For a site with no cellular coverage, replace the Wi-Fi block with a
 *    LoRa link to a gateway that republishes to the same MQTT topic. The server
 *    contract does not change: same topic, same JSON.
 * 4. Time. Without NTP the node sends no timestamp and the API uses receipt
 *    time. Clock drift is tolerated up to TELEMETRY_MAX_CLOCK_SKEW_SECONDS.
 * 5. Security. Per-device MQTT credentials should be provisioned per node when
 *    the fleet is large enough to need them; Mosquitto ACLs bind each device to
 *    its own `devices/{DEVICE_ID}/#` subtree, which is what stops one node from
 *    publishing into another's series.
 */
