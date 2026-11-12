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
- Bench test with dummy loads. Confirm power-off contactor OFF, flush valve opens and diversion goes to drain.
- Independently trip high-pressure and high-high-level switches with controller disconnected.
- Confirm distribution pump remains pressure-switch operated and has independent low-water cutoff.
- No live high-pressure tests until component ratings and safety devices validated.
