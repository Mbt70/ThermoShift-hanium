// ThermoShift ir_01 - MQTT IR bridge + cooling relay controller
//
// Cooling control path:
// Raspberry Pi Gateway -> MQTT -> ir_01 ESP32 -> GPIO26 -> relay module
// -> 12V Peltier/fans ON/OFF through the relay COM/NO contacts.
//
// ESP32 does not power the 12V load. It only drives the relay IN pin.
//
// Wiring:
// Relay IN  -> ESP32 GPIO26
// Relay VCC -> ESP32 5V
// Relay GND -> ESP32 GND
// IR_RX     -> ESP32 GPIO34
// IR_TX     -> ESP32 GPIO25
// IR_TX/RX VCC -> ESP32 3v3

// Cooling MQTT:
// Subscribe: thermoshift/ir_01/cooling/cmd
// Payload:   ON/on/1 -> relayOn()
//            OFF/off/0 -> relayOff()
// Publish:   thermoshift/ir_01/cooling/state, payload ON or OFF
//
// Existing IR MQTT commands are kept:
// - thermoshift/ir_01/control
// - esp32/device/env_01/control
// - esp32/device/ir_01/control

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ===================== User Config =====================

const char* WIFI_SSID = "ThermoShift-Local";
const char* WIFI_PASSWORD = "thermoshift1234";

const char* MQTT_SERVER = "10.42.0.1";
const int MQTT_PORT = 1883;
const char* MQTT_CLIENT_ID = "ir_01";

const char* CMD_TOPIC = "thermoshift/ir_01/cooling/cmd";
const char* STATE_TOPIC = "thermoshift/ir_01/cooling/state";

// Change only these two values if your relay module acts inverted.
// Low trigger relay: GPIO LOW = relay ON, GPIO HIGH = relay OFF.
const int RELAY_ON = LOW;
const int RELAY_OFF = HIGH;

// =======================================================

const char* NODE_ID = "ir_01";

const char* TOPIC_STATUS = "thermoshift/ir_01/status";
const char* TOPIC_RX = "thermoshift/ir_01/ir_rx";
const char* TOPIC_ERROR = "thermoshift/system/error";
const char* TOPIC_HEARTBEAT = "thermoshift/system/heartbeat";

// 브로커가 이 노드의 연결이 끊긴 것을 감지하면 대신 발행해 주는 유언(LWT).
// 이게 없으면 노드가 죽어도 TOPIC_STATUS 의 retained "online" 이 영원히 남아,
// 게이트웨이도 대시보드도 죽은 노드를 살아있다고 읽는다. 실제로 릴레이가
// 응답하지 않는데 status 는 online 이라 원인 파악이 늦어진 적이 있다.
const char* LWT_PAYLOAD =
    "{\"node\":\"ir_01\",\"status\":\"offline\","
    "\"detail\":\"broker detected disconnect (MQTT will)\","
    "\"cooling_relay\":\"UNKNOWN\"}";

const char* TOPIC_CONTROL_IR = "thermoshift/ir_01/control";
const char* TOPIC_CONTROL_ENV = "esp32/device/env_01/control";
const char* TOPIC_CONTROL_SELF = "esp32/device/ir_01/control";

const int RELAY_PIN = 26;
const uint8_t IR_RX_PIN = 34;
const uint8_t IR_TX_PIN = 25;

const uint32_t HEARTBEAT_INTERVAL_MS = 30000;
const uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
const uint32_t MQTT_RETRY_INTERVAL_MS = 2000;

WiFiClient espClient;
PubSubClient mqttClient(espClient);

uint32_t lastHeartbeatMs = 0;
uint32_t lastMqttReconnectAttemptMs = 0;
String lastCommand = "none";
bool relayIsOn = false;

int wifiRssiOrZero() {
  return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0;
}

// --------------------- Wi-Fi ---------------------

bool connectWiFi(uint32_t timeoutMs = WIFI_CONNECT_TIMEOUT_MS) {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  Serial.print("[ir_01] Connecting to WiFi SSID=");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[ir_01] WiFi connection failed");
    return false;
  }

  Serial.println("[ir_01] WiFi connected");
  Serial.print("[ir_01] IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("[ir_01] RSSI: ");
  Serial.println(WiFi.RSSI());
  return true;
}

// --------------------- MQTT Publish Helpers ---------------------

bool publishJson(const char* topic, StaticJsonDocument<512>& doc, bool retained = false) {
  if (!mqttClient.connected()) {
    return false;
  }

  char payload[512];
  size_t n = serializeJson(doc, payload, sizeof(payload));
  if (n == 0 || n >= sizeof(payload)) {
    Serial.println("[ir_01] JSON serialization failed or payload too large");
    return false;
  }

  bool ok = mqttClient.publish(topic, payload, retained);
  Serial.print("[ir_01] publish topic=");
  Serial.println(topic);
  Serial.println(payload);

  if (!ok) {
    Serial.println("[ir_01] MQTT publish failed");
  }

  return ok;
}

void publishStatus(const char* status, const char* detail = "", bool irTxOk = true) {
  StaticJsonDocument<512> doc;
  doc["node"] = NODE_ID;
  doc["status"] = status;
  doc["detail"] = detail;
  doc["last_cmd"] = lastCommand;
  doc["cooling_relay"] = relayIsOn ? "ON" : "OFF";
  doc["ir_tx_ok"] = irTxOk;
  doc["ir_rx_ok"] = true;
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();

  publishJson(TOPIC_STATUS, doc, true);
}

void publishError(const char* where, const char* message) {
  StaticJsonDocument<512> doc;
  doc["node"] = NODE_ID;
  doc["level"] = "error";
  doc["where"] = where;
  doc["message"] = message;
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();

  publishJson(TOPIC_ERROR, doc, false);
}

void publishRelayState(bool retained = true) {
  const char* state = relayIsOn ? "ON" : "OFF";
  bool ok = mqttClient.connected() && mqttClient.publish(STATE_TOPIC, state, retained);

  Serial.print("[ir_01] cooling relay state=");
  Serial.println(state);
  Serial.print("[ir_01] publish topic=");
  Serial.println(STATE_TOPIC);
  Serial.println(state);

  if (!ok) {
    Serial.println("[ir_01] cooling state publish failed");
  }
}

// --------------------- Relay Control ---------------------

void relayOn() {
  if (relayIsOn) {
    // 이미 켜져 있어도 상태를 다시 발행한다. 게이트웨이가 cooling/state 로
    // 명령 성사를 확인하는데, 여기서 조용히 return 하면 재전송이 영원히
    // 무응답으로 보인다.
    Serial.println("[ir_01] cooling relay already ON");
    publishRelayState(true);
    return;
  }

  digitalWrite(RELAY_PIN, RELAY_ON);
  relayIsOn = true;
  lastCommand = "cooling_on";

  Serial.println("[ir_01] cooling relay ON");
  publishRelayState(true);
}

void relayOff() {
  if (!relayIsOn) {
    Serial.println("[ir_01] cooling relay already OFF");
    publishRelayState(true);
    return;
  }

  digitalWrite(RELAY_PIN, RELAY_OFF);
  relayIsOn = false;
  lastCommand = "cooling_off";

  Serial.println("[ir_01] cooling relay OFF");
  publishRelayState(true);
}

void forceRelayOffAtBoot() {
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, RELAY_OFF);
  relayIsOn = false;
  Serial.println("[ir_01] cooling relay initialized OFF");
}

// 릴레이 명령을 하나의 상태 문자열로 정규화한다.
//   ON            (평문)
//   "ON"          (JSON 문자열로 감싼 경우)
//   {"state":"ON"}(오브젝트)
// 셋 다 같은 값으로 본다. 게이트웨이·프론트·수동 테스트가 서로 다른 형식을
// 보낸 적이 있는데, 평문만 받던 시절에는 나머지가 조용히 버려졌다.
bool extractCoolingState(const char* raw, String& out) {
  String text = String(raw);
  text.trim();

  if (text.startsWith("{")) {
    StaticJsonDocument<192> doc;
    if (deserializeJson(doc, text)) {
      return false;
    }
    const char* keys[] = {"state", "cooling", "command", "value", "cooling_relay"};
    for (const char* key : keys) {
      if (doc[key].is<const char*>()) {
        out = String((const char*)doc[key]);
        out.trim();
        return true;
      }
      if (doc[key].is<int>()) {
        out = String((int)doc[key]);
        return true;
      }
    }
    return false;
  }

  if (text.length() >= 2 && text.startsWith("\"") && text.endsWith("\"")) {
    text = text.substring(1, text.length() - 1);
    text.trim();
  }

  out = text;
  return true;
}

bool handleCoolingCommand(byte* payload, unsigned int length) {
  // retained 메시지를 지울 때 브로커가 빈 페이로드를 보낸다. 이건 명령이
  // 아니므로 에러로 올리지 않는다. 올리면 정리할 때마다 error 토픽이 튄다.
  if (length == 0) {
    Serial.println("[ir_01] empty cooling payload ignored (retained clear)");
    return true;
  }

  // 예전 버퍼는 16 바이트라 {"state":"ON"} 같은 JSON 이 잘려 들어왔다.
  char command[128];
  unsigned int copyLength = min(length, (unsigned int)(sizeof(command) - 1));

  for (unsigned int i = 0; i < copyLength; i++) {
    command[i] = (char)payload[i];
  }
  command[copyLength] = '\0';

  Serial.print("[ir_01] cooling command received: ");
  Serial.println(command);

  String cmd;
  if (!extractCoolingState(command, cmd)) {
    Serial.println("[ir_01] cooling command has no usable state field");
    publishError("handleCoolingCommand", "no state field in cooling command");
    return false;
  }

  if (cmd.equalsIgnoreCase("ON") || cmd == "1" || cmd.equalsIgnoreCase("true")) {
    relayOn();
    return true;
  }

  if (cmd.equalsIgnoreCase("OFF") || cmd == "0" || cmd.equalsIgnoreCase("false")) {
    relayOff();
    return true;
  }

  Serial.println("[ir_01] unknown cooling command. Expected ON/OFF/1/0");
  publishError("handleCoolingCommand", "unknown cooling command");
  return false;
}

// --------------------- IR Transmit / Receive ---------------------

uint64_t parseCode(const char* text) {
  if (text == nullptr) {
    return 0;
  }
  if (strlen(text) > 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) {
    return strtoull(text + 2, nullptr, 16);
  }
  return strtoull(text, nullptr, 10);
}

void irMark(uint32_t usec) {
  const uint32_t period = 26;  // 38 kHz, approx.
  const uint32_t halfPeriod = period / 2;
  uint32_t start = micros();

  while (micros() - start < usec) {
    digitalWrite(IR_TX_PIN, HIGH);
    delayMicroseconds(halfPeriod);
    digitalWrite(IR_TX_PIN, LOW);
    delayMicroseconds(halfPeriod);
  }
}

void irSpace(uint32_t usec) {
  digitalWrite(IR_TX_PIN, LOW);
  if (usec > 0) {
    delayMicroseconds(usec);
  }
}

void sendNecCode(uint64_t code, uint16_t bits) {
  irMark(9000);
  irSpace(4500);

  for (uint16_t i = 0; i < bits; i++) {
    irMark(560);
    if (code & ((uint64_t)1 << i)) {
      irSpace(1690);
    } else {
      irSpace(560);
    }
  }

  irMark(560);
  irSpace(0);
}

bool sendNecFromJson(JsonDocument& doc) {
  if (!doc["nec_code"].is<const char*>()) {
    return false;
  }

  uint64_t code = parseCode(doc["nec_code"]);
  uint16_t bits = doc["bits"] | 32;

  sendNecCode(code, bits);

  Serial.print("[ir_01] sent NEC code=0x");
  Serial.println((uint32_t)code, HEX);

  lastCommand = "nec";
  publishStatus("ir_sent", "NEC code sent", true);
  return true;
}

bool sendRawFromJson(JsonDocument& doc) {
  JsonArray raw = doc["raw"].as<JsonArray>();
  if (raw.isNull()) {
    return false;
  }

  uint16_t index = 0;
  for (JsonVariant value : raw) {
    uint16_t duration = value.as<uint16_t>();
    if (index % 2 == 0) {
      irMark(duration);
    } else {
      irSpace(duration);
    }
    index++;
    if (index >= 150) {
      break;
    }
  }
  irSpace(0);

  if (index == 0) {
    publishError("sendRawFromJson", "raw array is empty");
    return true;
  }

  Serial.print("[ir_01] sent raw count=");
  Serial.println(index);

  lastCommand = "raw";
  publishStatus("ir_sent", "raw IR sent", true);
  return true;
}

void handleAirconControl(JsonDocument& doc) {
  lastCommand = "aircon_control";

  StaticJsonDocument<512> status;
  status["node"] = NODE_ID;
  status["status"] = "command_received";
  status["detail"] = "aircon IR profile not configured yet";
  status["aircon_power"] = doc["aircon_power"] | "";
  status["aircon_temp"] = doc["aircon_temp"] | 0;
  status["aircon_mode"] = doc["aircon_mode"] | "";
  status["vent_fan"] = doc["vent_fan"] | "";
  status["cooling_relay"] = relayIsOn ? "ON" : "OFF";
  status["ir_tx_ok"] = false;
  status["ir_rx_ok"] = true;
  status["uptime_ms"] = millis();
  status["wifi_rssi"] = wifiRssiOrZero();

  publishJson(TOPIC_STATUS, status, true);
  Serial.println("[ir_01] aircon command received, but no IR profile is configured");
}

void handleIrCommand(byte* payload, unsigned int length) {
  StaticJsonDocument<768> doc;
  DeserializationError error = deserializeJson(doc, payload, length);
  if (error) {
    publishError("handleIrCommand", "invalid JSON command");
    return;
  }

  if (sendNecFromJson(doc)) {
    return;
  }

  if (sendRawFromJson(doc)) {
    return;
  }

  if (doc["aircon_power"].is<const char*>() || doc["aircon_temp"].is<float>() || doc["aircon_temp"].is<int>()) {
    handleAirconControl(doc);
    return;
  }

  lastCommand = "unknown";
  publishStatus("command_ignored", "unknown command format", false);
}

void publishReceivedNec(uint32_t code, uint16_t bits) {
  char hexCode[16];
  snprintf(hexCode, sizeof(hexCode), "0x%08lX", (unsigned long)code);

  StaticJsonDocument<512> doc;
  doc["node"] = NODE_ID;
  doc["protocol"] = "NEC";
  doc["value"] = hexCode;
  doc["bits"] = bits;
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();

  publishJson(TOPIC_RX, doc, false);

  Serial.print("[ir_01] IR received NEC value=");
  Serial.println(hexCode);
}

bool readNec(uint32_t& code) {
  // Typical demodulated IR receiver is idle HIGH and pulses LOW for marks.
  uint32_t leaderMark = pulseIn(IR_RX_PIN, LOW, 12000);
  if (leaderMark < 8000 || leaderMark > 10000) {
    return false;
  }

  uint32_t leaderSpace = pulseIn(IR_RX_PIN, HIGH, 6000);
  if (leaderSpace < 3500 || leaderSpace > 5500) {
    return false;
  }

  uint32_t value = 0;
  for (uint8_t i = 0; i < 32; i++) {
    uint32_t mark = pulseIn(IR_RX_PIN, LOW, 1500);
    uint32_t space = pulseIn(IR_RX_PIN, HIGH, 2500);
    if (mark < 300 || mark > 900) {
      return false;
    }
    if (space > 1000) {
      value |= ((uint32_t)1 << i);
    }
  }

  code = value;
  return true;
}

// --------------------- MQTT ---------------------

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("[ir_01] MQTT message topic=");
  Serial.println(topic);

  if (strcmp(topic, CMD_TOPIC) == 0) {
    handleCoolingCommand(payload, length);
    return;
  }

  handleIrCommand(payload, length);
}

bool reconnectMqtt() {
  if (mqttClient.connected()) {
    return true;
  }

  if (!connectWiFi()) {
    return false;
  }

  Serial.print("[ir_01] Connecting to MQTT ");
  Serial.print(MQTT_SERVER);
  Serial.print(":");
  Serial.println(MQTT_PORT);

  // willRetain=true 라야 나중에 붙는 구독자도 "이 노드는 죽어 있다"를 본다.
  if (!mqttClient.connect(MQTT_CLIENT_ID, nullptr, nullptr,
                          TOPIC_STATUS, 0, true, LWT_PAYLOAD)) {
    Serial.print("[ir_01] MQTT failed, rc=");
    Serial.println(mqttClient.state());
    return false;
  }

  mqttClient.subscribe(CMD_TOPIC);
  mqttClient.subscribe(TOPIC_CONTROL_IR);
  mqttClient.subscribe(TOPIC_CONTROL_ENV);
  mqttClient.subscribe(TOPIC_CONTROL_SELF);

  Serial.println("[ir_01] MQTT connected and subscribed");
  Serial.println(CMD_TOPIC);
  Serial.println(TOPIC_CONTROL_IR);
  Serial.println(TOPIC_CONTROL_ENV);
  Serial.println(TOPIC_CONTROL_SELF);

  publishStatus("online", "IR bridge and cooling relay ready", true);
  publishRelayState(true);
  return true;
}

void publishHeartbeat() {
  StaticJsonDocument<512> doc;
  doc["node"] = NODE_ID;
  doc["status"] = "online";
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();
  doc["cooling_relay"] = relayIsOn ? "ON" : "OFF";
  doc["ir_tx_ok"] = true;
  doc["ir_rx_ok"] = true;

  publishJson(TOPIC_HEARTBEAT, doc, false);
}

// --------------------- Arduino Lifecycle ---------------------

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("======================================");
  Serial.println(" ThermoShift ir_01 MQTT IR + Relay");
  Serial.println("======================================");

  forceRelayOffAtBoot();

  pinMode(IR_TX_PIN, OUTPUT);
  digitalWrite(IR_TX_PIN, LOW);
  pinMode(IR_RX_PIN, INPUT);

  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);
  mqttClient.setKeepAlive(30);
  mqttClient.setSocketTimeout(5);

  connectWiFi();
  reconnectMqtt();
}

void loop() {
  if (mqttClient.connected()) {
    mqttClient.loop();
  } else {
    uint32_t now = millis();
    if (now - lastMqttReconnectAttemptMs >= MQTT_RETRY_INTERVAL_MS) {
      lastMqttReconnectAttemptMs = now;
      reconnectMqtt();
    }
  }

  uint32_t receivedCode = 0;
  if (readNec(receivedCode)) {
    publishReceivedNec(receivedCode, 32);
  }

  uint32_t now = millis();
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    publishHeartbeat();
  }

  delay(20);
}
