# Sensor Node Local LCD Specification — Draft 0.3

## Purpose and scope
Add a local read-only status display to the ESP32 RS485/Modbus sensor node. LCD is an optional presentation device: no pump, valve, safety, measurement, or Modbus function may depend on it. No LCD buttons are required in the initial release.

## Candidate hardware (provisional)
- 20 columns x 4 rows HD44780-compatible character LCD with PCF8574 I2C backpack.
- Typical I2C addresses 0x27 or 0x3F, detected or configured; do not assume either is correct.
- Display may require 5 V; PCF8574 pull-ups may pull SDA/SCL to 5 V. **Do not connect 5 V I2C directly to ESP32 GPIO.** Use a bidirectional I2C level shifter, or verify a complete 3.3 V-compatible interface and logic thresholds. Check the backpack's pull-ups.
- Allocate SDA and SCL only after the actual sensor-node board GPIO pinout is confirmed. Use configurable pin constants; avoid boot strapping pins and conflicts with ADC, pulse counters, HX711, RS485, or flash/PSRAM.
- Place the LCD where it can be read during maintenance; provide strain relief and moisture protection as appropriate.

## Screens (20 characters per row; column 20 reserved)
**Column 20 rule (owner decision 2026-11-23):** on every page, normal, fault or diagnostic, column 20 of every row is reserved for a fault/status indicator. Page content uses columns 1-19. Column 20 is blank (space) in normal operation and `*` while any WARNING or CRITICAL fault is active (owner decision 2026-11-23); ADVISORY alone leaves it blank. Any HOLD marker is not designed yet (`docs/TODO.md`).

Page 1: water quality — feed EC, permeate EC, rejection percentage, permeate temperature.
Page 2: hydraulics — permeate GPM, concentrate GPM, recovery %, membrane feed PSI (if fitted).
Page 3: tank — estimated gallons, percent full, trend (filling/draining), weight sensor status.
Page 4: diagnostics — sensor-node uptime, Modbus communications, sensor validity, fault code.
Pages 5+: 1-Wire devices (protocol 1.4), after diagnostics; see "1-Wire pages" below.

Only display measurements that the sensor node actually knows. The node does not know the main controller's RO operating state unless the protocol is explicitly extended to report it. Until then show local measurement state, not guessed 'PRODUCTION' or 'STANDBY'. If a value is unavailable, stale, or invalid, display `--` or `ERR` instead of retaining the last good reading without a warning. No page may claim drinking-water safety based solely on EC/TDS.

## User interface behavior
- Rotate pages automatically every 5 seconds (configurable 3–15 seconds); optionally allow a fixed page through a local configuration constant.
- Refresh visible values approximately once per second; update only changed characters/rows to minimize I2C traffic and flicker.
- Display a concise fault indication immediately when critical sensor data is invalid; do not hide fault status behind page rotation.
- Show a short boot splash then transition to readings; initialize with finite timeouts.
- Backlight behavior configurable (always on initially); consider dimming later if hardware supports it.

## Firmware implementation contract
- New module `firmware/sensor_node/services/lcd_display.py`, with a thin driver adapter under `drivers/` for the selected I2C LCD library.
- Use a nonblocking scheduler or cooperative task; no blocking sleeps in acquisition or Modbus handling. Limit LCD operations per cycle and ensure slow/disconnected I2C cannot stall the sensor node.
- Render from a validated, immutable/copy snapshot of the same measurements published to Modbus; do not independently resample sensors inside display code.
- LCD exceptions are logged/counted; attempt bounded reinitialization at a conservative interval. Continue Modbus and sensor acquisition without a display.
- No changes to existing Modbus measurement addresses or scaling. If main-controller status is later sent to the node, define an explicit backward-compatible protocol extension with versioning.

## Acceptance tests
1. Boot and operate with LCD present; all pages fit 20x4 with content in columns 1-19 (column 20 reserved) and refresh.
2. Boot and operate with LCD unplugged or wrong I2C address; Modbus and sensor collection remain operational.
3. Force I2C timeout during active Modbus polling; no material effect on communications or pulse counts.
4. Inject invalid/stale sensor data; screen shows `--`/`ERR` and never stale unmarked values.
5. Power-cycle repeatedly; no GPIO boot conflict or unintentional actuator behavior.
6. Confirm level shifting and bus voltage with a meter before connecting ESP32 GPIO.
7. Confirm LCD uses no control authority: removing it does not change safety or RO logic.

## Open hardware decisions
Settled by ADR-0012: board (ESP32-S3-DevKitC-1-N16R8) and pins (I2C on GPIO8/9, `hardware/sensor-node/pinout.yaml`), I2C pull-ups and a PCA9306 level shifter for a 5 V backpack. Two diagnostic buttons (NEXT on GPIO10, HOLD on GPIO47) replace the page-select question; their behavior is in `docs/TODO.md`.

Still open: LCD backpack model and character ROM; LCD cable length (I2C rise time, bench check); enclosure mounting.

## 1-Wire pages (protocol 1.4, ADR-0011)
- **Placement:** 1-Wire pages join NORMAL rotation after the diagnostics page, 4 rows per page, as many pages as the present devices need (at most 4 pages for 8 DS2438s). They never preempt and never appear in fault pages. A 1-Wire bus fault stays an ADVISORY. Names never change fault priority.
- **Row layout (owner decision 2026-11-23):** label left-aligned in columns 1-11, a space in column 12, a 7-character right-aligned value in columns 13-19, and column 20 reserved for the fault/status indicator. A DS18B20 takes one row. A DS2438 takes two: label + temperature, then 12 spaces + mV value + column 20. Other families: label row with `    ---`.
- **Values:** temperature with one decimal plus `C` (no degree glyph, so output does not depend on the character ROM), e.g. `  21.5C`, ` -12.3C`; DS2438 voltage ` 3300mV`. Invalid or stale: `    ---`. A value that does not fit in 7 characters: `    ERR`.
- **Labels:** from the controller's name table (`protocol/ONEWIRE_NAME_TABLE.md`), 1-11 characters. An unnamed device shows `?` + family (2 hex digits) + `-` + the low 16 bits of the serial (4 hex digits), 8 characters: ROM `28FF1B2C3D5F4EDE` shows `?28-1BFF`.
- **Charset:** labels use printable ASCII 0x20-0x7D except `\` (0x5C) and `~` (0x7E). This assumes the common HD44780 A00 character ROM (the exact LCD is TBD), where 0x5C renders as ¥ and 0x7E as an arrow.
- **Example page:**
```
 00000000011111111112   column number, tens digit
 12345678901234567890   column number, units digit (brackets enclose the 20 columns)
[?28-7A31        --- ]  stale DS18B20, unnamed (ROM 28317A0000000014)
[Tank air      22.1C ]  DS2438 "Tank air" (ROM 26D4C3B2A10000DE), temperature
[             3300mV ]  same DS2438, voltage row
[Outside air   21.5C ]  DS18B20 "Outside air" (ROM 28FF1B2C3D5F4EDE)
```
A fifth row, `[?28-BEEF     -12.3C ]` (unnamed DS18B20, ROM 28EFBE00000000FE), goes to the next page. Column 20 is blank here (normal operation; it shows `*` during a WARNING or CRITICAL fault). These rows were produced by `render_onewire_rows` in `host_tools/src/ro_tools/onewire_names.py`, not written by hand.

## Draft 0.4 superseding display policy
The fault-first behavior in `EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md` supersedes unconditional page rotation and any older LCD fault-handling guidance. The optional main-controller status extension is now specified in `protocol/CONTROLLER_STATUS_EXTENSION.md`.
