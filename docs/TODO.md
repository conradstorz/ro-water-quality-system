# TODO

Future work that is not yet specified. Each item needs a design (and an ADR if it changes hardware, protocol or safety behavior) before implementation.

## Sensor-node diagnostic push buttons (2 buttons)
Added 2026-11-23. Two local push buttons on the sensor node for diagnosing sensor issues. Supersedes the open question in `docs/specs/SENSOR_NODE_LCD_SPEC.md` about a page-select button.

To define:
- **Purpose of each button:** for example, button 1 steps through diagnostic pages and button 2 selects or holds a page. Decide whether short press, long press and both-held gestures are used.
- **Diagnostic content:** per-channel raw values (ADC counts, pulse counts, HX711 counts, loop mA), validity, fault and installed bits, age of last sample, 1-Wire slot status and ROM IDs, calibration revision, Modbus link statistics.
- **Interaction with the exception-driven LCD:**
  - Does a diagnostic view time out back to normal rotation?
  - Must a CRITICAL fault still preempt it? The expected answer is yes.
  - See `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md`.
- **Behavior without an LCD:** do the buttons do anything, such as an LED blink code or a USB log dump?
- **Authority limits.** Buttons are local display and diagnostics only. They must never:
  - command a pump or valve;
  - clear a controller fault or latch;
  - change calibration or the node ID;
  - alter Modbus registers or the published snapshot.
  
  Whether any maintenance action (for example, entering calibration mode) is ever allowed needs its own safety review.
- **Hardware:**
  - GPIO assignment, avoiding strapping pins, ADC1 (GPIO1 is used by pressure, ADR-0010), PCNT, I2C, RS485 and 1-Wire pins.
  - Pull-up/pull-down choice, debounce (hardware RC or firmware), ESD protection.
  - Panel-mount, waterproof button type, enclosure position and labeling.
- **Firmware:** nonblocking button service, debounce timing, stuck-button detection (a stuck button must not lock the display), host-side tests with a mock input.
- **Docs to update when defined:** sensor-node hardware spec, both LCD specs, `LCD_FAULT_PRIORITY_TESTS.md`, acceptance test plan, CHANGELOG.
