# Industrial main controller hardware
Candidate: Amazon listing B0FBKH9YPM industrial 8-channel ESP32-S3 DIN-rail relay board; final manufacturer/model and manual TBD.
Received 2026-11-12: box label reads Waveshare `ESP32-S3-ETH-8DI-8RO` (non-PoE, RS485 variant). Vendor manual, pin map, demo code, datasheets and open questions are in `reference/README.md`; nothing there is bench-verified yet.
Advertised: 8 relays <=10A 250VAC / 30VDC (resistive contact rating), isolated digital inputs, isolated RS485, W5500 Ethernet, RTC, TF card, 7–36V input, USB-C, header.
**Verify:** actual terminal/pinout, Modbus UART routing, RS485 termination/bias, relay GPIO and boot behavior, isolated input electrical thresholds, firmware flashing/recovery, actual input count, relay motor/inductive load derating, safety approvals.
Proposed relays: K1 motor-rated booster contactor coil control; K2 12V flush actuator; K3 12V permeate diversion; K4 alarm; K5–K8 spare. Independent safety contacts wired in series with pump-enable circuit. No direct 120VAC motor switching via board relay.
Power: 12V main supply to 7–36V board input; 5V regulated rail for sensor electronics as required; do not backfeed USB and external input without checking manual.
