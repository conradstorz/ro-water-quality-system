# ADR-0001: Main ESP32-S3 + RS485 sensor node
**Accepted as design baseline (2026-11-10).**
Use industrial ESP32-S3 relay controller for actuation, safety-status inputs, networking, and system state machine. Use a second ESP32 as Modbus RTU sensor server. Motivation: main board may lack exposed GPIO; isolate sensor acquisition complexity; preserve modularity. Main controller owns decisions. Independent hardwired safety remains essential.
