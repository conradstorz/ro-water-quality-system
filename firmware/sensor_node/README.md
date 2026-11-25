# Sensor ESP32 firmware
Implementation placeholder. Drivers, coherent acquisition snapshots, Modbus RTU server, calibration store, and health status must follow the subsystem specification. Runtime: ADR-0007. Do not put actuator logic here.

## First slice: one DS18B20 over RS485 (agreed 2026-11-25)
Production firmware increment on temporary bench wiring: bare ESP32-S3 board on USB power, no 24 V trunk, pump or valves. Master: PC with a USB-RS485 adapter.

**In scope**
- Full 100-199 input block as one atomic snapshot, and holding 200-202. The node reports protocol 1.3.
- C++ register codec generated from `protocol/register_map.yaml`; logic in a framework-independent library tested with the `native` env.
- One DS18B20 in a 1-Wire slot, behind a driver interface. Every other channel is not installed.
- `module_status` operational, `critical_age_ms` and `sensor_error_code` as in spec section 5.
- Task watchdog, `boot_counter` and watchdog-reset reporting.

**Deferred:** controller status block (220-227), 1-Wire name table (240-322), calibration store, DS2482 driver, LCD and buttons.

**Done when**
- `ro-tools read --serial` shows the live probe temperature.
- Unplugging the probe clears its slot's valid bit and no stale value is shown as good.
- Illegal function codes and addresses and bad CRCs are rejected.
- A one-hour polling run has no CRC errors or timeouts (needs a polling loop in `ro-tools`).
- Host tests run the Python client against the host-built C++ codec.

## Bench wiring (temporary, not the carrier pin map)
- DS18B20, three-wire power (not parasitic): VDD to 3V3, GND to GND, DQ to GPIO38, 4.7 kohm from DQ to 3V3. Keep the lead short; there is no ESD or short protection.
- Node ID 1: 10 kohm pull-ups to 3V3 on GPIO4-7, and GPIO4 linked to GND. With no link the node stays silent.
- RS485 module: sold as "TTL RS485 XY-485". Identify its chip before powering it: use 3V3 for a 3.3 V part (SP3485 or MAX3485); stop if it is a MAX485. UART1 TX GPIO17 to the module's receive input, RX GPIO18 from its transmit output.

**TBD (check before wiring):** the module's chip marking; whether it switches direction automatically (if so, GPIO21 is unused); what its TXD/RXD labels mean; whether it has its own 120 ohm termination or bias; A/B polarity against the USB adapter.
