# Sensor Node Local LCD Specification — Draft 0.3

## Purpose and scope
Add a local read-only status display to the ESP32 RS485/Modbus sensor node. LCD is an optional presentation device: no pump, valve, safety, measurement, or Modbus function may depend on it. No LCD buttons are required in the initial release.

## Candidate hardware (provisional)
- 20 columns x 4 rows HD44780-compatible character LCD with PCF8574 I2C backpack.
- Typical I2C addresses 0x27 or 0x3F, detected or configured; do not assume either is correct.
- Display may require 5 V; PCF8574 pull-ups may pull SDA/SCL to 5 V. **Do not connect 5 V I2C directly to ESP32 GPIO.** Use a bidirectional I2C level shifter, or verify a complete 3.3 V-compatible interface and logic thresholds. Check the backpack's pull-ups.
- Allocate SDA and SCL only after the actual sensor-node board GPIO pinout is confirmed. Use configurable pin constants; avoid boot strapping pins and conflicts with ADC, pulse counters, HX711, RS485, or flash/PSRAM.
- Place the LCD where it can be read during maintenance; provide strain relief and moisture protection as appropriate.

## Screens (20 characters maximum per row)
Page 1: water quality — feed EC, permeate EC, rejection percentage, permeate temperature.
Page 2: hydraulics — permeate GPM, concentrate GPM, recovery %, membrane feed PSI (if fitted).
Page 3: tank — estimated gallons, percent full, trend (filling/draining), weight sensor status.
Page 4: diagnostics — sensor-node uptime, Modbus communications, sensor validity, fault code.

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
1. Boot and operate with LCD present; all pages fit 20x4 and refresh.
2. Boot and operate with LCD unplugged or wrong I2C address; Modbus and sensor collection remain operational.
3. Force I2C timeout during active Modbus polling; no material effect on communications or pulse counts.
4. Inject invalid/stale sensor data; screen shows `--`/`ERR` and never stale unmarked values.
5. Power-cycle repeatedly; no GPIO boot conflict or unintentional actuator behavior.
6. Confirm level shifting and bus voltage with a meter before connecting ESP32 GPIO.
7. Confirm LCD uses no control authority: removing it does not change safety or RO logic.

## Open hardware decisions
Exact sensor ESP32 board and pins; LCD backpack model and voltage; I2C pull-up arrangement; cable length; enclosure mounting; whether a local page-select button is desirable in a later revision.

## Draft 0.4 superseding display policy
The fault-first behavior in `EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md` supersedes unconditional page rotation and any older LCD fault-handling guidance. The optional main-controller status extension is now specified in `protocol/CONTROLLER_STATUS_EXTENSION.md`.
