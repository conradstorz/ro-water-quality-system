# ADR-0004 — Local LCD on sensor node

**Status:** Accepted in principle, pending electrical pinout verification.

Add a 20x4 I2C character LCD to the sensor ESP32 for on-site visibility. It is a read-only, non-safety-critical peripheral, fed from the sensor node's existing validated measurement snapshot. Loss of the LCD must never stop sensor acquisition or Modbus communication. See `docs/specs/SENSOR_NODE_LCD_SPEC.md`.
