#include <Wire.h>

#define MPU9250_ADDR 0x68
#define ACCEL_CONFIG 0x1C
#define GYRO_CONFIG 0x1B
#define ACCEL_XOUT_H 0x3B
#define GYRO_XOUT_H 0x43

void setup() {
  Serial.begin(115200);
  Wire.begin();
  Wire.setClock(400000);

  Wire.beginTransmission(MPU9250_ADDR);
  Wire.write(0x6B);
  Wire.write(0x00);
  Wire.endTransmission();
  delay(100);
}

void loop() {
  int16_t ax, ay, az, gx, gy, gz;

  Wire.beginTransmission(MPU9250_ADDR);
  Wire.write(ACCEL_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU9250_ADDR, 6);
  ax = (Wire.read() << 8) | Wire.read();
  ay = (Wire.read() << 8) | Wire.read();
  az = (Wire.read() << 8) | Wire.read();

  Wire.beginTransmission(MPU9250_ADDR);
  Wire.write(GYRO_XOUT_H);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU9250_ADDR, 6);
  gx = (Wire.read() << 8) | Wire.read();
  gy = (Wire.read() << 8) | Wire.read();
  gz = (Wire.read() << 8) | Wire.read();

  float ax_g = ax / 16384.0;
  float ay_g = ay / 16384.0;
  float az_g = az / 16384.0;
  float gx_dps = gx / 131.0;
  float gy_dps = gy / 131.0;
  float gz_dps = gz / 131.0;

  Serial.print(ax_g, 4);
  Serial.print(",");
  Serial.print(ay_g, 4);
  Serial.print(",");
  Serial.print(az_g, 4);
  Serial.print(",");
  Serial.print(gx_dps, 4);
  Serial.print(",");
  Serial.print(gy_dps, 4);
  Serial.print(",");
  Serial.println(gz_dps, 4);

  delay(50);   // 20 Hz
}