/*
  ESP32 다중 센서 노드 - MQTT 연동 스케치
  
  * 필수 설치 라이브러리 (Arduino IDE 라이브러리 매니저에서 설치):
    1. PubSubClient (by Nick O'Leary) - MQTT 통신용
    2. ArduinoJson (by Benoit Blanchon) - JSON 페이로드 빌드용
    3. Adafruit SHT31 Library (by Adafruit) - SHT31 온습도 센서용
    4. Sensirion I2C SCD4x (by Sensirion) - SCD41 CO2/온습도 센서용
*/

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <SensirionI2cScd4x.h>

// 1. Wi-Fi 설정
const char* ssid = "thermoshift_ap";
const char* password = "thermoshift1234";

// 고정 IP 설정 (필요 시 true로 설정하고 기기별로 IP 주소를 다르게 설정하세요)
const bool use_static_ip = false;
IPAddress local_IP(192, 168, 4, 181); // 예: env_01.ino=181, env_02.ino=182, ir_01.ino=183, occ_01.ino=184
IPAddress gateway(192, 168, 4, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress dns_primary(192, 168, 4, 1);
IPAddress dns_secondary(0, 0, 0, 0);

// 2. Raspberry Pi MQTT 브로커 IP 및 포트
const char* mqtt_server = "192.168.4.1"; 
const int mqtt_port = 1883;

// 3. 기기 고유 ID 설정 (라즈베리파이 백엔드에서 이 ID로 데이터를 분류합니다)
const char* device_id = "livingroom"; 

// 4. MQTT 토픽 설정
// esp32/device/<device_id>/state
char mqtt_topic[50];

// 5. 핀 맵 구성
#define PIR_PIN 27       // PIR 인체 감지 센서 핀
#define DOOR_PIN 26      // 마그네틱 문 센서 핀 (GPIO 26)

// 6. 센서 주기 설정
unsigned long lastMsgTime = 0;
const unsigned long sendInterval = 10000; // 10초 주기 데이터 전송
// =============================================

WiFiClient espClient;
PubSubClient client(espClient);
Adafruit_SHT31 sht31 = Adafruit_SHT31();
SensirionI2cScd4x scd4x;

// 인터럽트 혹은 디텍션 처리를 위한 변수
volatile bool motionDetected = false;
volatile bool doorStateChanged = false;
int lastDoorState = -1;

// PIR 센서 ISR (인터럽트 서비스 루틴)
void IRAM_ATTR handleMotion() {
  motionDetected = true;
}

// 문 센서 ISR
void IRAM_ATTR handleDoor() {
  doorStateChanged = true;
}

void setup() {
  Serial.begin(115200);
  
  // MQTT 토픽 동적 생성
  snprintf(mqtt_topic, sizeof(mqtt_topic), "esp32/device/%s/state", device_id);
  
  // 핀 모드 설정
  pinMode(PIR_PIN, INPUT_PULLDOWN); // PIR 센서 타입에 따라 PULLUP/PULLDOWN 조정 필요
  pinMode(DOOR_PIN, INPUT_PULLUP);  // 문 센서는 일반적으로 Pullup 권장 (GND와 접점 확인)
  
  // 문 초기 상태 기록
  lastDoorState = digitalRead(DOOR_PIN);

  // 인터럽트 설정 (움직임 감지 및 문 개폐 변화 시 즉각 MQTT 전송용)
  attachInterrupt(digitalPinToInterrupt(PIR_PIN), handleMotion, RISING);
  attachInterrupt(digitalPinToInterrupt(DOOR_PIN), handleDoor, CHANGE);

  // I2C 시작
  Wire.begin();

  // SHT31 센서 초기화
  if (!sht31.begin(0x44)) {   // 보통 SHT31의 I2C 기본 주소는 0x44 또는 0x45
    Serial.println("SHT31 센서를 찾을 수 없습니다. 연결을 확인하세요.");
  } else {
    Serial.println("SHT31 온습도 센서 초기화 성공.");
  }

  // SCD41 센서 초기화
  scd4x.begin(Wire);
  uint16_t error;
  char errorMessage[256];
  // SCD41 측정 정지 (설정 변경을 위해)
  error = scd4x.stopPeriodicMeasurement();
  if (error) {
    Serial.print("SCD41 정지 실패: ");
    errorToString(error, errorMessage, 256);
    Serial.println(errorMessage);
  }
  // 주기 측정 시작
  error = scd4x.startPeriodicMeasurement();
  if (error) {
    Serial.print("SCD41 시작 실패: ");
    errorToString(error, errorMessage, 256);
    Serial.println(errorMessage);
  } else {
    Serial.println("SCD41 CO2 센서 초기화 성공.");
  }

  // Wi-Fi 연결
  setup_wifi();

  // MQTT 브로커 연결 정보 설정
  client.setServer(mqtt_server, mqtt_port);
}

void setup_wifi() {
  delay(10);
  Serial.println();
  Serial.print("Wi-Fi 연결 중: ");
  Serial.println(ssid);

  if (use_static_ip) {
    if (!WiFi.config(local_IP, gateway, subnet, dns_primary, dns_secondary)) {
      Serial.println("고정 IP 설정 실패!");
    } else {
      Serial.println("고정 IP 설정 적용됨.");
    }
  }

  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("");
  Serial.println("Wi-Fi 연결 성공!");
  Serial.print("IP 주소: ");
  Serial.println(WiFi.localIP());
}

// MQTT 브로커 재접속
void reconnect() {
  while (!client.connected()) {
    Serial.print("MQTT 브로커 연결 시도...");
    // 랜덤 클라이언트 ID 생성
    String clientId = "ESP32Client-" + String(random(0xffff), HEX);
    
    if (client.connect(clientId.c_str())) {
      Serial.println("연결 완료!");
    } else {
      Serial.print("실패, rc=");
      Serial.print(client.state());
      Serial.println(" 5초 후 재시도...");
      delay(5000);
    }
  }
}

// 센서 데이터를 읽고 MQTT로 전송하는 함수
void sendSensorData(bool forceSendEvent = false) {
  // Wi-Fi 또는 MQTT 연결 상태 점검
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // JSON 문서 생성 (크기는 필드 수에 따라 적절하게 조절)
  StaticJsonDocument<256> doc;
  doc["device_id"] = device_id;
  
  // 1. SHT31 데이터 읽기
  float temp_sht = sht31.readTemperature();
  float hum_sht = sht31.readHumidity();
  if (!isnan(temp_sht)) doc["temperature"] = round(temp_sht * 10) / 10.0;
  if (!isnan(hum_sht)) doc["humidity"] = round(hum_sht * 10) / 10.0;

  // 2. SCD41 데이터 읽기 (CO2 센서)
  uint16_t co2 = 0;
  float temp_scd = 0.0;
  float hum_scd = 0.0;
  bool isScdDataReady = false;
  
  scd4x.getDataReadyStatus(isScdDataReady);
  if (isScdDataReady) {
    uint16_t err = scd4x.readMeasurement(co2, temp_scd, hum_scd);
    if (!err && co2 > 0) {
      doc["co2"] = co2;
      // SHT31이 없을 때만 SCD41의 온습도로 대체하거나, 혹은 둘 다 있다면 SHT31을 우선적으로 사용
      if (isnan(temp_sht)) {
        doc["temperature"] = round(temp_scd * 10) / 10.0;
        doc["humidity"] = round(hum_scd * 10) / 10.0;
      }
    }
  }

  // 3. PIR 센서 값 (0: 움직임 없음, 1: 움직임 감지)
  int pirVal = digitalRead(PIR_PIN);
  doc["motion"] = pirVal;

  // 4. 문 센서 개폐 값 (0: 닫힘, 1: 열림)
  // Pullup 설계이므로 일반적으로 HIGH(1)가 열림, LOW(0)가 닫힘
  int doorVal = digitalRead(DOOR_PIN);
  doc["door_open"] = (doorVal == HIGH) ? 1 : 0;

  // 5. Wi-Fi 신호 감도 (RSSI)
  doc["rssi"] = WiFi.RSSI();

  // JSON을 문자열로 직렬화
  char buffer[256];
  serializeJson(doc, buffer);

  // MQTT 토픽으로 데이터 발행
  Serial.print("데이터 전송 [");
  Serial.print(mqtt_topic);
  Serial.print("]: ");
  Serial.println(buffer);
  
  client.publish(mqtt_topic, buffer);
}

void loop() {
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  unsigned long now = millis();

  // A. 움직임 감지 이벤트 발생 시 즉각 전송
  if (motionDetected) {
    Serial.println(">> 이벤트 감지: 움직임 감지됨!");
    motionDetected = false;
    sendSensorData(true);
  }

  // B. 문 개폐 이벤트 발생 시 즉각 전송
  if (doorStateChanged) {
    int currentDoorState = digitalRead(DOOR_PIN);
    if (currentDoorState != lastDoorState) {
      Serial.println(">> 이벤트 감지: 문 개폐 상태 변동!");
      lastDoorState = currentDoorState;
      sendSensorData(true);
    }
    doorStateChanged = false;
  }

  // C. 주기적인 일반 데이터 센싱 전송
  if (now - lastMsgTime > sendInterval) {
    lastMsgTime = now;
    sendSensorData();
  }

  delay(100); // 루프 딜레이
}
