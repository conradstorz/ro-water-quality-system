# TODO

Future work that is not yet specified. Each item needs a design (and an ADR if it changes hardware, protocol or safety behavior) before implementation.

## Sensor-node diagnostic push buttons (2 buttons)
Added 2026-11-23. Two local push buttons on the sensor node for diagnosing sensor issues. Supersedes the open question in `docs/specs/SENSOR_NODE_LCD_SPEC.md` about a page-select button.

Owner's intended behavior (2026-11-23):
- **Button 1 (NEXT):** advances the display to the next page in the normal sequence and restarts the automatic page rotation from that page, including when the display was frozen.
- **Button 2 (HOLD):** freezes the display on the current page. Auto-advance stops; the page keeps refreshing its live values.

Open questions about that behavior:
- Pressing HOLD while already frozen: no effect, or unfreeze?
- Does a freeze time out back to auto rotation (and after how long), or stay until NEXT is pressed?
- A CRITICAL or WARNING fault preempts a frozen page, as the fault-first LCD spec requires. When the fault clears, does the display go back to the frozen page or resume rotation?
- Are diagnostic pages part of the normal sequence, or a separate set reached by a long press or both buttons together?
- Should the screen show a visible HOLD indicator (for example, a character in a corner) while frozen?

To define:
- **Gestures beyond the above:** whether long press or both-held are used.
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
