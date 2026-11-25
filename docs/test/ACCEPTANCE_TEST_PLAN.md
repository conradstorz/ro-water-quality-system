# Acceptance test plan
## Protocol
- Confirm 19200 8E1, unit 1, function 04 input block, function 03 metadata, exception responses and CRC.
- Test zero-based offsets, 16-bit signed decoding, 32-bit high-word-first counters, saturation/overflow flags, coherent snapshots, version mismatch.
- Test disconnect, CRC corruption, bus contention, restart, sequence rollover, 3-second stale-data inhibit.
## Sensors
- Conductivity low/high standards, compensation, out-of-range and missing probe.
- Flow pulse calibration for each channel; no-flow vs broken sensor, startup and flush regimes.
- Two HX711 tare/gain and known gallons; fill/drain hysteresis and hinge effects.
- Pressure gauge comparison, disconnect and ADC saturation.
## RO feed pressure (monitoring only, ADR-0010)
- Inject 4.0, 12.0 and 20.0 mA with a loop calibrator; confirm 0, 116.0 and 232.1 psi (0.40, 1.20 and 2.00 V at GPIO1) within calibration tolerance (TBD).
- Measure the LM317 limit with P+ shorted to P- (expect about 29 mA, 28-30 mA) and the GPIO1 voltage (expect below 3.0 V).
- Open loop (0 mA), shorted transmitter terminals and overrange (> 20.5 mA): each sets fault bit 5 and clears validity bit 6; the 24 V trunk and other nodes stay up.
- P- shorted to +24 V through a current-limited bench supply: PTC trips, GPIO1 stays clamped, ESP32 keeps running.
- With pressure not installed, no pressure fault is raised. With any pressure fault, `production_permitted` is unchanged unless the controller config requires pressure.
## 1-Wire (monitoring only, ADR-0009)
- Device add: a new device appears and `onewire_scan_generation` increments, `onewire_device_count` rises. Slots are sorted by ROM ascending, so a new device with a lower ROM shifts the indices of the others; controller bindings are by ROM, never by slot index.
- Device remove: the slot stays with `missing` set and `present` clear; count falls; generation increments.
- Overflow: more than 8 devices reports the 8 lowest ROM IDs and sets `bus_status` bit 3.
- CRC error: `crc_error` set, value words zero and `valid` clear. Bus faults (short, no presence): `bus_status` bit set and `onewire_bus_fault` (fault bit 10) raised; slot contents are undefined and a consumer must treat all slots as unusable (do not assert specific slot values).
- Unsupported family: ROM ID only, value words zero, `valid` clear.
- No effect on production gating: with any 1-Wire fault injected, `production_permitted` is identical to the no-fault result, and 1-Wire bits are absent from validity and critical masks.
- Plug labeling: confirm "1-WIRE" plugs cannot be mistaken for the RJ45 RO BUS and are routed away from 24 V and RS485 wiring.
## 1-Wire device names (display only, ADR-0011)
- Push a valid name table, then write an invalid one (bad ROM CRC, all-zero ROM, 12-character label, non-zero unused entry, partial write): each is rejected with a Modbus exception and an FC03 read-back still returns the prior table.
- Reboot the node: the table reads back empty; the controller sees the `boot_counter` change and re-pushes, and the read-back matches.
- Against a protocol 1.3 node: the write answers ILLEGAL_DATA_ADDRESS, the controller reports names unsupported (`ro-tools onewire push` exit 4), does not retry until `boot_counter` changes, and `production_permitted` and node health are identical to the no-write case.
- With names pushed, the LCD shows each label in columns 1-11 with column 20 free; unnamed devices show `?FF-SSSS`.

## Sensor-node power (ADR-0012)
- USB operating rule (owner decision 2026-11-25): connect USB only while the 24 V trunk is powered; for USB work without trunk power, take the board out of the carrier first. The carrier has no diode between its 5 V rail and the board's 5Vin pin.
- With the trunk powered, measure 5V_CARRIER (expect 5.22-5.40 V) and the 1117 input during Wi-Fi TX bursts (must stay at or above 4.60 V; ADR-0012 section 2.1).
- With the trunk powered and USB connected, confirm no current flows from 5V_CARRIER into the USB host (SL diode orientation).

## Actuators and safety
- Bench test with dummy loads. Confirm power-off contactor OFF and flush valve opens. Diversion valve (K3, normally closed) is closed when unpowered; confirm it energizes to drain only while the controller commands a dump.
- Permeate diversion (ADR-0006): startup dump until EC below threshold then switch to tank; high permeate EC during production switches to dump and raises a fault; dump-time limit triggers the configured fault; stale or invalid EC inhibits production (rule 4). Thresholds and limits TBD.
- Measure permeate-side back pressure at the membrane port with the line full, running and after shutdown; confirm it stays within the membrane datasheet limit.
- Independently trip high-pressure and high-high-level switches with controller disconnected.
- Confirm distribution pump remains pressure-switch operated and has independent low-water cutoff.
- No live high-pressure tests until component ratings and safety devices validated.
