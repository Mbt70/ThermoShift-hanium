#define DOOR_PIN 23

void setup() {
  Serial.begin(115200);
  pinMode(DOOR_PIN, INPUT_PULLUP);
}

void loop() {
  if (digitalRead(DOOR_PIN) == LOW) {
    Serial.println("Door CLOSED");
  } else {
    Serial.println("Door OPEN");
  }

  delay(300);
}

