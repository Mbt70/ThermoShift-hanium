// ThermoShift occ_01 - MQTT occupancy node
//
// Wiring:
// door_main -> GPIO23
// door_sub  -> GPIO5
// pir_door  -> GPIO18
//
// Magnetic reed switch:
// one side -> GPIO pin
// other side -> GND
// code uses INPUT_PULLUP, so closed=0 and open=1.
//
// PIR:
// OUT -> GPIO18
// VCC -> module-rated power, usually 3V3 or 5V
// GND -> GND

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

const char* WIFI_SSID = "ThermoShift-Local";
const char* WIFI_PASSWORD = "thermoshift1234";

const char* MQTT_SERVER = "10.42.0.1";
const int MQTT_PORT = 1883;

const char* NODE_ID = "occ_01";
const char* MQTT_TOPIC = "thermoshift/occ/occ_01";

const int DOOR_MAIN_PIN = 23;
const int DOOR_SUB_PIN = 5;
const int PIR_DOOR_PIN = 18;

WiFiClient espClient;
PubSubClient mqttClient(espClient);

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[occ_01] Connecting to WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("[occ_01] WiFi connected");
  Serial.print("[occ_01] IP: ");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("[occ_01] Connecting to MQTT... ");

    if (mqttClient.connect(NODE_ID)) {
      Serial.println("connected");
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 2 seconds");
      delay(2000);
    }
  }
}

int readDoorState(int pin) {
  return digitalRead(pin) == HIGH ? 1 : 0;  // 1=open, 0=closed
}

int readPirState(int pin) {
  return digitalRead(pin) == HIGH ? 1 : 0;  // 1=motion, 0=no motion
}

void publishOccData() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[occ_01] WiFi disconnected. Reconnecting...");
    connectWiFi();
  }

  if (!mqttClient.connected()) {
    connectMQTT();
  }

  int doorMain = readDoorState(DOOR_MAIN_PIN);
  int doorSub = readDoorState(DOOR_SUB_PIN);
  int pirDoor = readPirState(PIR_DOOR_PIN);

  StaticJsonDocument<256> doc;
  doc["node"] = NODE_ID;
  doc["pir_door"] = pirDoor;
  doc["pir_seat"] = -1;
  doc["door_main"] = doorMain;
  doc["door_sub"] = doorSub;

  char payload[256];
  serializeJson(doc, payload, sizeof(payload));

  bool ok = mqttClient.publish(MQTT_TOPIC, payload);

  Serial.println("[occ_01] MQTT publish payload:");
  Serial.println(payload);

  if (ok) {
    Serial.println("[occ_01] MQTT publish success");
  } else {
    Serial.println("[occ_01] MQTT publish failed");
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("[occ_01] Booting...");

  pinMode(DOOR_MAIN_PIN, INPUT_PULLUP);
  pinMode(DOOR_SUB_PIN, INPUT_PULLUP);
  pinMode(PIR_DOOR_PIN, INPUT);

  connectWiFi();

  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  connectMQTT();
}

void loop() {
  mqttClient.loop();
  publishOccData();
  delay(1000);
}
