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
## 1-Wire (monitoring only, ADR-0009)
- Device add: a new device appears and `onewire_scan_generation` increments, `onewire_device_count` rises. Slots are sorted by ROM ascending, so a new device with a lower ROM shifts the indices of the others; controller bindings are by ROM, never by slot index.
- Device remove: the slot stays with `missing` set and `present` clear; count falls; generation increments.
- Overflow: more than 8 devices reports the 8 lowest ROM IDs and sets `bus_status` bit 3.
- CRC error: `crc_error` set, value words zero and `valid` clear. Bus faults (short, no presence): `bus_status` bit set and `onewire_bus_fault` (fault bit 10) raised; slot contents are undefined and a consumer must treat all slots as unusable (do not assert specific slot values).
- Unsupported family: ROM ID only, value words zero, `valid` clear.
- No effect on production gating: with any 1-Wire fault injected, `production_permitted` is identical to the no-fault result, and 1-Wire bits are absent from validity and critical masks.
- Plug labeling: confirm "1-WIRE" plugs cannot be mistaken for the RJ45 RO BUS and are routed away from 24 V and RS485 wiring.

## Actuators and safety
- Bench test with dummy loads. Confirm power-off contactor OFF and flush valve opens. Diversion valve (K3, normally closed) is closed when unpowered; confirm it energizes to drain only while the controller commands a dump.
- Permeate diversion (ADR-0006): startup dump until EC below threshold then switch to tank; high permeate EC during production switches to dump and raises a fault; dump-time limit triggers the configured fault; stale or invalid EC inhibits production (rule 4). Thresholds and limits TBD.
- Measure permeate-side back pressure at the membrane port with the line full, running and after shutdown; confirm it stays within the membrane datasheet limit.
- Independently trip high-pressure and high-high-level switches with controller disconnected.
- Confirm distribution pump remains pressure-switch operated and has independent low-water cutoff.
- No live high-pressure tests until component ratings and safety devices validated.
