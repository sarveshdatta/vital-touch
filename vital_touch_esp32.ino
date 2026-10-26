/*
 * Vital Touch - ESP32 + MAX30102 firmware
 *
 * Reads heart rate and SpO2 from a MAX30102 (SparkFun MAX3010x library,
 * Maxim reference algorithm) and posts every valid reading to the Vital Touch
 * backend over WiFi. Readings that cannot be sent are kept in a small queue
 * and retried, so short WiFi drops do not lose data.
 *
 * Libraries (Arduino Library Manager):
 *   - "SparkFun MAX3010x Pulse and Proximity Sensor Library"
 *   - "Adafruit MLX90614 Library"  (only if USE_MLX90614 is 1)
 * Board: ESP32 Dev Module (esp32 core by Espressif)
 *
 * Setup: copy config.example.h to config.h and fill in WiFi + backend details.
 */

#include <Wire.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include "MAX30105.h"          // SparkFun library; class also supports MAX30102
#include "spo2_algorithm.h"
#include "config.h"

#if USE_MLX90614
#include <Adafruit_MLX90614.h>
Adafruit_MLX90614 mlx;
#endif

MAX30105 particleSensor;

// ---- Sensor configuration ----
// The Maxim algorithm in spo2_algorithm.h assumes 25 samples per second.
// sampleRate 100 with sampleAverage 4 gives exactly 25 samples per second.
// (The previous sketch used the library defaults, 100 samples/s effective,
//  which makes the computed heart rate unreliable.)
const byte LED_BRIGHTNESS = 60;   // 0 = off ... 255 = 50 mA
const byte SAMPLE_AVERAGE = 4;
const byte LED_MODE       = 2;    // 2 = Red + IR
const int  SAMPLE_RATE    = 100;
const int  PULSE_WIDTH    = 411;
const int  ADC_RANGE      = 4096;

const int I2C_SDA = 21;
const int I2C_SCL = 22;

const uint32_t FINGER_IR_THRESHOLD = 50000;   // IR below this = no finger on sensor
#define BUFFER_LENGTH 100                      // 4 s of data at 25 samples/s

uint32_t irBuffer[BUFFER_LENGTH];
uint32_t redBuffer[BUFFER_LENGTH];

// ---- Offline queue ----
struct Reading {
  int32_t heartRate;
  int32_t spo2;
  float   temperature;
  bool    hasTemperature;
};

const int QUEUE_SIZE = 20;
Reading queue[QUEUE_SIZE];
int queueHead = 0;
int queueCount = 0;

void enqueue(const Reading &r) {
  if (queueCount == QUEUE_SIZE) {            // full: drop the oldest reading
    queueHead = (queueHead + 1) % QUEUE_SIZE;
    queueCount--;
  }
  queue[(queueHead + queueCount) % QUEUE_SIZE] = r;
  queueCount++;
}

// ---- Networking ----
void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to WiFi \"%s\"", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    delay(500);
    Serial.print('.');
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected" : " failed, will retry");
}

// Returns true when the reading should be removed from the queue
// (accepted, or permanently rejected by the server). Returns false on
// network errors / server errors so the reading is retried later.
bool postReading(const Reading &r) {
  if (WiFi.status() != WL_CONNECTED) return false;

  char body[160];
  if (r.hasTemperature) {
    snprintf(body, sizeof(body),
             "{\"device_id\":\"%s\",\"heart_rate\":%ld,\"spo2\":%ld,\"temperature\":%.1f}",
             DEVICE_ID, (long)r.heartRate, (long)r.spo2, r.temperature);
  } else {
    snprintf(body, sizeof(body),
             "{\"device_id\":\"%s\",\"heart_rate\":%ld,\"spo2\":%ld}",
             DEVICE_ID, (long)r.heartRate, (long)r.spo2);
  }

  HTTPClient http;
  http.begin(String(BACKEND_URL) + "/api/readings");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", DEVICE_API_KEY);
  int code = http.POST((uint8_t *)body, strlen(body));
  http.end();

  Serial.printf("POST %s -> %d\n", body, code);
  if (code == 201) return true;
  if (code >= 400 && code < 500) {
    Serial.println("Server rejected the reading (check API key / values); dropping it.");
    return true;
  }
  return false;
}

void flushQueue() {
  while (queueCount > 0) {
    if (!postReading(queue[queueHead])) break;   // keep it for the next attempt
    queueHead = (queueHead + 1) % QUEUE_SIZE;
    queueCount--;
  }
}

// ---- Arduino entry points ----
void setup() {
  Serial.begin(115200);
  Wire.begin(I2C_SDA, I2C_SCL);
  Serial.println("Vital Touch starting...");

  if (!particleSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found. Check wiring (SDA 21, SCL 22, 3.3 V).");
    while (true) delay(1000);
  }
  particleSensor.setup(LED_BRIGHTNESS, SAMPLE_AVERAGE, LED_MODE,
                       SAMPLE_RATE, PULSE_WIDTH, ADC_RANGE);

#if USE_MLX90614
  if (!mlx.begin()) {
    Serial.println("MLX90614 not found; continuing without temperature.");
  }
#endif

  connectWiFi();
  Serial.println("Place your finger on the sensor...");
}

void loop() {
  // 1. Collect 4 seconds of samples
  for (byte i = 0; i < BUFFER_LENGTH; i++) {
    while (!particleSensor.available()) particleSensor.check();
    redBuffer[i] = particleSensor.getRed();
    irBuffer[i]  = particleSensor.getIR();
    particleSensor.nextSample();
  }

  // 2. Skip when no finger is on the sensor
  if (irBuffer[BUFFER_LENGTH - 1] < FINGER_IR_THRESHOLD) {
    Serial.println("No finger detected.");
    connectWiFi();
    flushQueue();
    return;
  }

  // 3. Compute heart rate and SpO2
  int32_t spo2, heartRate;
  int8_t validSpo2, validHeartRate;
  maxim_heart_rate_and_oxygen_saturation(irBuffer, BUFFER_LENGTH, redBuffer,
                                         &spo2, &validSpo2, &heartRate, &validHeartRate);

  bool plausible = validHeartRate && validSpo2 &&
                   heartRate >= 30 && heartRate <= 220 &&
                   spo2 >= 70 && spo2 <= 100;
  if (!plausible) {
    Serial.println("Unstable reading (movement?), skipped.");
    connectWiFi();
    flushQueue();
    return;
  }

  Reading r = { heartRate, spo2, 0.0f, false };
#if USE_MLX90614
  float t = mlx.readObjectTempC();
  if (!isnan(t)) {
    r.temperature = t;
    r.hasTemperature = true;
  }
#endif

  Serial.printf("HR=%ld bpm  SpO2=%ld %%\n", (long)heartRate, (long)spo2);

  // 4. Queue and send (anything queued during a WiFi drop is sent first)
  enqueue(r);
  connectWiFi();
  flushQueue();
}
