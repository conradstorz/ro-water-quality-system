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
  - GPIO assignment: NEXT on GPIO10, HOLD on GPIO47 (ADR-0012).
  - Pull-up, debounce and ESD: 10 kohm pull-up, 100 nF, 1 kohm, TPD1E10B06; firmware debounce 20 ms (ADR-0012, section 7).
  - Panel-mount, waterproof button type, enclosure position and labeling.
- **Firmware:** nonblocking button service, debounce timing, stuck-button detection (a stuck button must not lock the display), host-side tests with a mock input.
- **Docs to update when defined:** sensor-node hardware spec, both LCD specs, `LCD_FAULT_PRIORITY_TESTS.md`, acceptance test plan, CHANGELOG.

## Exact hardware specification
Added 2026-11-23. Replace every hardware TBD with a specific part, value or measured figure. Record the decisions in ADRs like ADR-0010 (circuit, parts list, arithmetic checked by a test), and update the specs listed under each item. AGENTS.md rule 5 still applies: owner facts and datasheets, never guesses.

### Owner to supply (model number, listing link, or "not chosen yet")
- [ ] **Main controller:** confirm the Waveshare ESP32-S3-ETH-8DI-8RO (Amazon B0FBKH9YPM) and its manual. Then size fuse F1 (`hardware/main-controller/HARDWARE_SPEC.md`, `WIRING.md`).
- [ ] **Sensor-node ESP32-S3 board**, if one is already owned (`hardware/sensor-node/HARDWARE_SPEC.md`).
- [ ] **Flow meters (permeate, concentrate):** pulse output type and voltage, K-factor, and whether temperature is built in and how it is read (Modbus spec temperature rows).
- [ ] **Conductivity probes and modules (feed, permeate):** range (the permeate low range must be verified), output signal, supply.
- [ ] **Tank load cells and HX711 boards:** capacity, excitation, mounting.
- [ ] **Flush valve and permeate diversion valve:** model, voltage, coil current and inrush, duty cycle, fail state. The USS-MSV00072 is provisional. Then size F2 and settle the 12 V rail (ADR-0006, `WIRING.md`).
- [ ] **Pump contactor:** coil voltage and current. **Booster pump** model.
- [ ] **RO membrane** datasheet: permeate back-pressure limit (`docs/safety/SAFETY_REQUIREMENTS.md`), recovery limit.
- [ ] **Plumbing:** pressure ratings, low-crack check valve, relief discharge routing (`hardware/plumbing/PROCESS_AND_INSTRUMENTATION.md`).
- [ ] **Power supplies:** 24 V (trunk and controller) and 12 V (valves, coil) models and ratings (`hardware/power/POWER_AND_WIRING.md`).
- [ ] **LCD module:** 20×4 I²C backpack part and its character ROM (A00 assumption in ADR-0011).
- [ ] **Trunk cable and 1-Wire connector:** RJ45 cable type, and the Nilight connector's cavity numbering and ratings.

### Claude to design (sensor-node carrier board; no owner facts needed)
Designed 2026-11-23 in `docs/decisions/ADR-0012-sensor-node-carrier.md` (Proposed). Where a design part is done but an owner fact remains, the box is ticked and the remaining fact is noted.
- [x] Full GPIO map for the ESP32-S3 carrier: avoid strapping pins (0, 3, 45, 46), USB (19/20) and JTAG (39-42); keep GPIO1 for pressure (ADR-0010); reserve two GPIOs for the diagnostic buttons (section above). Recorded in `hardware/sensor-node/pinout.yaml` (generic ESP32-S3 N16R8 board, DevKitC-1 pin-compatible, owner-supplied 2026-11-25; buttons on GPIO10 and GPIO47).
- [x] Trunk input stage: fuse, reverse-polarity protection, TVS, 24→5 V buck, 3.3 V regulator, per-node current budget. Budget 305.6 mA from 24 V; confirm by measurement in Stage D. 3.3 V comes from the board's 1117 LDO, fed directly from the buck at 5.31 V; D2 deleted, USB only while the trunk is powered (reworked 2026-11-25).
- [x] RS485: transceiver part, bias resistor values at the controller, termination plan including the controller's jumper (ADR-0008). Whether bias is fitted depends on the Stage D idle-bus check.
- [x] Pulse inputs: level conditioning and protection into PCNT. Universal front end done. **Remaining owner fact:** flow-meter output type, voltage and supply, which set the two jumpers.
- [x] 1-Wire front end: DS2482-100 master (no GPIO), series resistor, pull-up, polyfuse rating, ESD/TVS (ADR-0009). **Remaining owner fact:** Nilight connector cavity numbering and ratings.
- [x] ADS1115 (EC and thermistors) and HX711 wiring, I²C addresses, input protection. **Remaining owner facts:** EC module output range (the divider covers up to 5.5 V), thermistor nominal resistance (sets Rref), load-cell bridge resistance.
- [x] DIP-switch node-ID input; LCD I²C connection; push-button inputs and debounce. Panel button model and position stay with the enclosure layout.
- [x] Carrier BOM with part numbers; DIN-rail enclosure and connectors. **Remaining:** the enclosure model and dimensions, and terminal-block catalog numbers, chosen at layout.

### Bench measurements (Stage D)
- [ ] Maximum trunk length, voltage drop, per-node current.
- [ ] Idle-bus bias check; whether the controller board already biases RS485.
- [ ] 1-Wire maximum cable length and device count.
- [ ] Sensor-node ESP32-S3 board (ADR-0012, Stage D list): RGB LED GPIO; whether 5Vin passes through an SL diode; SL diode orientation (USB back-feed); IN-OUT and USB-OTG jumpers open; 1117 temperature and actual dropout; 3V3 oscillation; USB plus trunk coexistence. (Genuine N16R8 and CH343 bridge closed 2026-11-25 by esptool.) Owner facts: EC modules, LCD module and any 5 V flow meter must accept 5.40 V.
- [ ] Pressure loop: limiter current, ADC at 4/12/20 mA, shorted and open loop (acceptance plan).

### Firmware-side TBDs tied to hardware
- [ ] Pinned Arduino-ESP32 and PlatformIO versions; Modbus RTU library choice (ADR-0007).
- [ ] EC acceptance threshold for dump→tank, maximum dump time (ADR-0006).
- [ ] Pressure calibration tolerance (acceptance plan).
