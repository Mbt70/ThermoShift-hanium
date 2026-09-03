// ThermoShift env_01 - SCD41 MQTT Publisher
//
// Wiring:
// ESP32 GPIO21 -> SCD41 SDA
// ESP32 GPIO22 -> SCD41 SCL
// SCD41 VCC   -> ESP32 3V3
// SCD41 GND   -> ESP32 GND
//
// MQTT Topic Rule:
// thermoshift/{node_id}/{sensor_id}
// Example:
// thermoshift/env_01/scd41_main

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <SensirionI2cScd4x.h>

#if __has_include("../secrets.h")
#include "../secrets.h"
#else
#error "Copy firmware/secrets.example.h to firmware/secrets.h and configure Wi-Fi credentials"
#endif

// ===================== User Config =====================

// Wi-Fi: Raspberry Pi와 같은 네트워크여야 함
const char* WIFI_SSID = THERMOSHIFT_WIFI_SSID;
const char* WIFI_PASSWORD = THERMOSHIFT_WIFI_PASSWORD;

// Static IP configuration
#define USE_STATIC_IP false  // Set to true to enable the static ESP32 IP below.
IPAddress local_IP(192, 168, 4, 181);
IPAddress gateway(192, 168, 4, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);
IPAddress secondaryDNS(8, 8, 4, 4);

// Raspberry Pi IP
// Pi에서 hostname -I 로 확인한 IP를 넣기
const char* MQTT_SERVER = "10.42.0.1";
const int MQTT_PORT = 1883;

// Node / Sensor ID
const char* NODE_ID = "env_01";
const char* SENSOR_ID = "scd41_main";

// MQTT topics
const char* TOPIC_SCD41 = "thermoshift/env_01/scd41_main";
const char* TOPIC_ENV_DATA = "thermoshift/env_01/data";
const char* TOPIC_STATUS = "thermoshift/env_01/status";
const char* TOPIC_HEARTBEAT = "thermoshift/system/heartbeat";
const char* TOPIC_ERROR = "thermoshift/system/error";

// I2C pins
const int I2C_SDA_PIN = 21;
const int I2C_SCL_PIN = 22;

// Publish intervals
const uint32_t SENSOR_PUBLISH_INTERVAL_MS = 5000;   // SCD41 측정 주기: 약 5초
const uint32_t HEARTBEAT_INTERVAL_MS = 30000;       // 상태 전송: 30초

// Wi-Fi / MQTT reconnect
const uint32_t WIFI_CONNECT_TIMEOUT_MS = 20000;
const uint8_t MQTT_MAX_ATTEMPTS = 5;

// =======================================================

WiFiClient espClient;
PubSubClient mqttClient(espClient);
SensirionI2cScd4x scd4x;

#ifdef NO_ERROR
#undef NO_ERROR
#endif
#define NO_ERROR 0

static char errorMessage[128];

bool scd41Ready = false;
uint32_t lastSensorPublishMs = 0;
uint32_t lastHeartbeatMs = 0;

// --------------------- Utility ---------------------

void printSCD41Error(const char* label, int16_t error) {
  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.print("] ");
  Serial.print(label);
  Serial.print(" error: ");
  errorToString(error, errorMessage, sizeof(errorMessage));
  Serial.println(errorMessage);
}

void makeClientId(char* buffer, size_t bufferSize) {
  uint64_t mac = ESP.getEfuseMac();
  snprintf(buffer, bufferSize, "%s-%04X%08X",
           NODE_ID,
           (uint16_t)(mac >> 32),
           (uint32_t)mac);
}

int wifiRssiOrZero() {
  if (WiFi.status() == WL_CONNECTED) {
    return WiFi.RSSI();
  }
  return 0;
}

// --------------------- Wi-Fi ---------------------

bool connectWiFi(uint32_t timeoutMs = WIFI_CONNECT_TIMEOUT_MS) {
  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // MQTT 안정성을 위해 Wi-Fi sleep 비활성화

  if (USE_STATIC_IP) {
    if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS)) {
      Serial.print("[");
      Serial.print(NODE_ID);
      Serial.println("] Static IP configuration failed");
    }
  }

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.print("] Connecting to Wi-Fi SSID=");
  Serial.println(WIFI_SSID);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.println("] Wi-Fi connected");

    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.print("] ESP32 IP: ");
    Serial.println(WiFi.localIP());

    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.print("] RSSI: ");
    Serial.println(WiFi.RSSI());

    return true;
  }

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.println("] Wi-Fi connection failed");

  return false;
}

// --------------------- MQTT ---------------------

bool connectMQTT(uint8_t maxAttempts = MQTT_MAX_ATTEMPTS) {
  if (mqttClient.connected()) {
    return true;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (!connectWiFi()) {
      return false;
    }
  }

  char clientId[64];
  makeClientId(clientId, sizeof(clientId));

  for (uint8_t attempt = 1; attempt <= maxAttempts; attempt++) {
    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.print("] Connecting to MQTT ");
    Serial.print(MQTT_SERVER);
    Serial.print(":");
    Serial.print(MQTT_PORT);
    Serial.print(" attempt ");
    Serial.print(attempt);
    Serial.print("/");
    Serial.println(maxAttempts);

    if (mqttClient.connect(clientId)) {
      Serial.print("[");
      Serial.print(NODE_ID);
      Serial.println("] MQTT connected");

      // Online status publish
      StaticJsonDocument<256> doc;
      doc["node"] = NODE_ID;
      doc["status"] = "online";
      doc["ip"] = WiFi.localIP().toString();
      doc["wifi_rssi"] = WiFi.RSSI();
      doc["uptime_ms"] = millis();

      char payload[256];
      serializeJson(doc, payload, sizeof(payload));
      mqttClient.publish(TOPIC_STATUS, payload, true);  // retained status

      return true;
    }

    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.print("] MQTT failed, rc=");
    Serial.println(mqttClient.state());

    delay(2000);
  }

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.println("] MQTT connection failed after retries");

  return false;
}

bool publishJson(const char* topic, StaticJsonDocument<384>& doc, bool retained = false) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[env_01] Wi-Fi disconnected. Reconnecting...");
    if (!connectWiFi()) {
      return false;
    }
  }

  if (!mqttClient.connected()) {
    if (!connectMQTT()) {
      return false;
    }
  }

  char payload[384];
  size_t n = serializeJson(doc, payload, sizeof(payload));

  if (n == 0 || n >= sizeof(payload)) {
    Serial.println("[env_01] JSON serialization failed or payload too large");
    return false;
  }

  bool ok = mqttClient.publish(topic, payload, retained);

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.print("] publish topic=");
  Serial.println(topic);
  Serial.println(payload);

  if (!ok) {
    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.println("] MQTT publish failed");
  }

  return ok;
}

void publishError(const char* where, const char* message) {
  StaticJsonDocument<384> doc;
  doc["node"] = NODE_ID;
  doc["level"] = "error";
  doc["where"] = where;
  doc["message"] = message;
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();

  publishJson(TOPIC_ERROR, doc, false);
}

void publishHeartbeat() {
  StaticJsonDocument<384> doc;
  doc["node"] = NODE_ID;
  doc["status"] = "online";
  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();
  doc["scd41_ready"] = scd41Ready;

  publishJson(TOPIC_HEARTBEAT, doc, false);
}

// --------------------- SCD41 ---------------------

bool setupSCD41() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  Wire.setClock(100000);  // 안정성을 위해 100 kHz

  scd4x.begin(Wire, SCD41_I2C_ADDR_62);

  int16_t error;
  uint64_t serialNumber = 0;

  delay(30);

  // 센서 초기화
  error = scd4x.wakeUp();
  if (error != NO_ERROR) {
    printSCD41Error("wakeUp", error);
    // wakeUp은 상황에 따라 에러가 나도 계속 진행 가능
  }

  error = scd4x.stopPeriodicMeasurement();
  if (error != NO_ERROR) {
    printSCD41Error("stopPeriodicMeasurement", error);
    // 이미 측정 중이 아니면 에러가 날 수 있으므로 계속 진행
  }

  delay(500);

  error = scd4x.reinit();
  if (error != NO_ERROR) {
    printSCD41Error("reinit", error);
    publishError("setupSCD41", "SCD41 reinit failed");
    return false;
  }

  delay(30);

  error = scd4x.getSerialNumber(serialNumber);
  if (error != NO_ERROR) {
    printSCD41Error("getSerialNumber", error);
    Serial.println("[env_01] Check wiring: VCC=3V3, GND, SDA=21, SCL=22");
    publishError("setupSCD41", "SCD41 serial number read failed. Check wiring.");
    return false;
  }

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.print("] SCD41 serial number: 0x");
  Serial.print((uint16_t)(serialNumber >> 32), HEX);
  Serial.print((uint32_t)serialNumber, HEX);
  Serial.println();

  error = scd4x.startPeriodicMeasurement();
  if (error != NO_ERROR) {
    printSCD41Error("startPeriodicMeasurement", error);
    publishError("setupSCD41", "SCD41 startPeriodicMeasurement failed");
    return false;
  }

  Serial.print("[");
  Serial.print(NODE_ID);
  Serial.println("] SCD41 periodic measurement started");

  return true;
}

bool readSCD41(uint16_t& co2, float& tempC, float& humidityRh) {
  if (!scd41Ready) {
    return false;
  }

  int16_t error;
  bool dataReady = false;

  error = scd4x.getDataReadyStatus(dataReady);
  if (error != NO_ERROR) {
    printSCD41Error("getDataReadyStatus", error);
    publishError("readSCD41", "getDataReadyStatus failed");
    return false;
  }

  if (!dataReady) {
    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.println("] SCD41 data not ready yet");
    return false;
  }

  error = scd4x.readMeasurement(co2, tempC, humidityRh);
  if (error != NO_ERROR) {
    printSCD41Error("readMeasurement", error);
    publishError("readSCD41", "readMeasurement failed");
    return false;
  }

  if (co2 == 0) {
    Serial.print("[");
    Serial.print(NODE_ID);
    Serial.println("] Invalid SCD41 sample: CO2 is 0");
    return false;
  }

  return true;
}

bool publishSCD41Data(uint16_t co2, float tempC, float humidityRh) {
  StaticJsonDocument<384> doc;

  doc["node"] = NODE_ID;
  doc["sensor"] = SENSOR_ID;
  doc["type"] = "co2_temperature_humidity";

  doc["co2_ppm"] = co2;
  doc["temp_c"] = tempC;
  doc["humidity_rh"] = humidityRh;

  doc["uptime_ms"] = millis();
  doc["wifi_rssi"] = wifiRssiOrZero();

  bool detailedOk = publishJson(TOPIC_SCD41, doc, false);

  StaticJsonDocument<384> dashboardDoc;
  dashboardDoc["node"] = NODE_ID;
  dashboardDoc["temperature"] = tempC;
  dashboardDoc["humidity"] = humidityRh;
  dashboardDoc["co2"] = co2;
  dashboardDoc["uptime_ms"] = millis();
  dashboardDoc["wifi_rssi"] = wifiRssiOrZero();

  bool dashboardOk = publishJson(TOPIC_ENV_DATA, dashboardDoc, false);

  return detailedOk && dashboardOk;
}

// --------------------- Arduino Lifecycle ---------------------

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("======================================");
  Serial.println(" ThermoShift env_01 SCD41 MQTT Node");
  Serial.println("======================================");

  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(512);
  mqttClient.setKeepAlive(30);
  mqttClient.setSocketTimeout(5);

  connectWiFi();
  connectMQTT();

  scd41Ready = setupSCD41();

  if (!scd41Ready) {
    Serial.println("[env_01] SCD41 setup failed. Sensor reads will be skipped.");
  }

  publishHeartbeat();
}

void loop() {
  // MQTT loop 유지
  if (mqttClient.connected()) {
    mqttClient.loop();
  } else {
    connectMQTT(1);
  }

  uint32_t now = millis();

  // Heartbeat
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    publishHeartbeat();
  }

  // Sensor publish
  if (now - lastSensorPublishMs >= SENSOR_PUBLISH_INTERVAL_MS) {
    lastSensorPublishMs = now;

    uint16_t co2 = 0;
    float tempC = 0.0f;
    float humidityRh = 0.0f;

    if (readSCD41(co2, tempC, humidityRh)) {
      Serial.print("[env_01] CO2=");
      Serial.print(co2);
      Serial.print(" ppm, Temp=");
      Serial.print(tempC);
      Serial.print(" C, RH=");
      Serial.print(humidityRh);
      Serial.println(" %");

      publishSCD41Data(co2, tempC, humidityRh);
    }
  }

  delay(50);
}
