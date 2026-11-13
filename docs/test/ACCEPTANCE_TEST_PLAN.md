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
## Actuators and safety
- Bench test with dummy loads. Confirm power-off contactor OFF and flush valve opens. Diversion valve (K3, normally closed) is closed when unpowered; confirm it energizes to drain only while the controller commands a dump.
- Permeate diversion (ADR-0006): startup dump until EC below threshold then switch to tank; high permeate EC during production switches to dump and raises a fault; dump-time limit triggers the configured fault; stale or invalid EC inhibits production (rule 4). Thresholds and limits TBD.
- Measure permeate-side back pressure at the membrane port with the line full, running and after shutdown; confirm it stays within the membrane datasheet limit.
- Independently trip high-pressure and high-high-level switches with controller disconnected.
- Confirm distribution pump remains pressure-switch operated and has independent low-water cutoff.
- No live high-pressure tests until component ratings and safety devices validated.
