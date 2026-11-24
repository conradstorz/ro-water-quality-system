# TODO

Future work that is not yet specified. Each item needs a design (and an ADR if it changes hardware, protocol or safety behavior) before implementation.

## Sensor-node diagnostic push buttons (2 buttons)
Added 2026-11-23. Two local push buttons on the sensor node for diagnosing sensor issues. Supersedes the open question in `docs/specs/SENSOR_NODE_LCD_SPEC.md` about a page-select button.

Owner's intended behavior (2026-11-23):
- **Button 1 (NEXT):** advances the display to the next page in the normal sequence and restarts the automatic page rotation from that page, including when the display was frozen.
- **Button 2 (HOLD):** freezes the display on the current page. Auto-advance stops; the page keeps refreshing its live values.

Owner decisions (2026-11-23):
- **HOLD toggles:** pressing HOLD while frozen unfreezes and auto rotation resumes.
- **No freeze timeout:** the display stays frozen until HOLD or NEXT is pressed.
- **Faults never steal focus from a held page.** Every screen, held or rotating, shows a fault indicator character or warning text while any fault is active.
- **Not held:** fault pages preempt rotation as today, and rotation resumes when the fault clears.
- **Fault indicator position (closed 2026-11-23, option A):** column 20 of every row on every page is reserved for the fault/status indicator; page content uses columns 1-19. 1-Wire rows are label 11 + space + value 7 + column 20 (ADR-0011). Recorded in both LCD specs.
- **Indicator glyph (closed 2026-11-23):** column 20 is a space in normal operation and `*` while any WARNING or CRITICAL fault is active, on every page including a held one. ADVISORY alone leaves it blank.

**Spec conflict to resolve when this is designed:** `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md` currently requires a CRITICAL fault to preempt the current page immediately and stay until resolved. Held pages are an owner-approved exception. Amend that spec, its acceptance test 2, and `docs/test/LCD_FAULT_PRIORITY_TESTS.md`.

The change is acceptable because the LCD is not part of any safety mechanism: the main controller and hardwired protections act regardless of what the display shows.

Remaining open questions:
- **Existing layouts that do not yet fit columns 1-19:** `STARTING / DATA WAIT` is 20 characters, and `RO STATE: <state>` exceeds 19 for `production` (20), `maintenance` (21), `startup_flush` (23) and `shutdown_flush` (24) if the enum names are shown as-is; the last three already exceeded 20 (`EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md`). They need shorter wording.
- **HOLD marker:** should the screen show one while frozen, and where?
- **Diagnostic pages:** part of the normal sequence, or a separate set reached by a long press or both buttons together?

To define:
- **Gestures beyond the above:** whether long press or both-held are used.
- **Diagnostic content:** per-channel raw values (ADC counts, pulse counts, HX711 counts, loop mA), validity, fault and installed bits, age of last sample, 1-Wire slot status and ROM IDs, calibration revision, Modbus link statistics.
- **Interaction with the exception-driven LCD:**
  - Does a diagnostic view time out back to normal rotation?
  - A held page is never preempted (owner decision above); an unheld one follows the fault-first rules.
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
