#include <WiFi.h>
#include <WiFiUdp.h>
#include <BleMouse.h>

const char* ssid        = "suryansh";
const char* password    = "suryansh";
const char* udpAddress  = "192.168.137.91";
const int   udpPort     = 5000;
const int   wifiTimeout = 20000;

// Smoothing parameters for BLE mouse
const float SMOOTHING_BLE   = 0.8;
const float SENSITIVITY_BLE = 0.8;
const float THRESHOLD_BLE   = 5.0;

WiFiUDP udp;
BleMouse bleMouse;
bool useWiFi = false;
bool useBLE  = false;

float smooth_x = 0.0;
float smooth_y = 0.0;

void setup() {
  Serial.begin(115200);
  Serial2.begin(115200);

  // Flush any garbage bytes from Arduino boot
  delay(500);
  while (Serial2.available()) {
    Serial2.read();
  }

  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  unsigned long startAttemptTime = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - startAttemptTime) < wifiTimeout) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    useWiFi = true;
    Serial.println("\nWiFi connected!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
    udp.begin(udpPort);
    Serial.println("UDP ready, waiting for data from Arduino...");
  } else {
    useBLE = true;
    Serial.println("\nWiFi connection failed. Switching to BLE Mouse mode...");
    bleMouse.begin();
    Serial.println("BLE Mouse ready. Pair with 'ESP32 Bluetooth Mouse' in your device settings.");
  }
}

void loop() {
  if (Serial2.available()) {
    String line = Serial2.readStringUntil('\n');
    line.trim(); // Remove \r, spaces, newlines

    if (line.length() < 10) return;        // Skip too-short lines
    if (line.indexOf(',') == -1) return;   // Skip lines with no commas

    if (useWiFi) {
      udp.beginPacket(udpAddress, udpPort);
      udp.print(line);
      udp.endPacket();
      Serial.println("Sent (UDP): " + line);

    } else if (useBLE) {
      float ax, ay, az, gx, gy, gz;
      int left = 0, right = 0, scrollMode = 0;

      int parsed = sscanf(line.c_str(), "%f,%f,%f,%f,%f,%f,%d,%d,%d",
                          &ax, &ay, &az, &gx, &gy, &gz, &left, &right, &scrollMode);

      if (parsed >= 6) {
        float raw_x = gz;
        float raw_y = gy;

        // Exponential smoothing
        smooth_x = SMOOTHING_BLE * raw_x + (1.0 - SMOOTHING_BLE) * smooth_x;
        smooth_y = SMOOTHING_BLE * raw_y + (1.0 - SMOOTHING_BLE) * smooth_y;

        // Apply sensitivity
        float move_x = smooth_x * SENSITIVITY_BLE;
        float move_y = smooth_y * SENSITIVITY_BLE;

        // Apply dead zone
        if (abs(smooth_x) < THRESHOLD_BLE) move_x = 0;
        if (abs(smooth_y) < THRESHOLD_BLE) move_y = 0;

        // Invert axes
        move_x = -move_x;
        move_y = -move_y;

        if (bleMouse.isConnected()) {
          if (scrollMode == 1) {
            int scrollAmount = (int)move_y;
            if (scrollAmount != 0) {
              bleMouse.move(0, 0, scrollAmount);
            }
          } else {
            int dx = (int)move_x;
            int dy = (int)move_y;
            if (dx != 0 || dy != 0) {
              bleMouse.move(dx, dy);
            }
          }

          // Button handling
          static int lastLeft = 0, lastRight = 0;
          if (left  && !lastLeft)  bleMouse.press(MOUSE_LEFT);
          if (!left  && lastLeft)  bleMouse.release(MOUSE_LEFT);
          if (right && !lastRight) bleMouse.press(MOUSE_RIGHT);
          if (!right && lastRight) bleMouse.release(MOUSE_RIGHT);
          lastLeft  = left;
          lastRight = right;

        } else {
          // Not connected yet — print reminder every 5 seconds
          static unsigned long lastPrint = 0;
          if (millis() - lastPrint > 5000) {
            Serial.println("Waiting for BLE connection...");
            lastPrint = millis();
          }
        }

      } else {
        // Only log parse errors for lines that look like they should be valid
        if (parsed > 0) {
          Serial.println("BLE parse error (got " + String(parsed) + " fields): " + line);
        }
      }
    }
  }
}