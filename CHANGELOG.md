# Changelog
## 0.1 — 2026-11-10
- Initial Git-ready architecture, subsystem spec, Modbus contract, hardware and safety scaffolding.

## Draft 0.3
- Added optional 20x4 I2C sensor-node LCD specification and ADR-0004.

## Draft 0.4 — 2026-11-11
- Specified exception-driven LCD fault priority, deterministic arbitration, controller-status freshness, and fail-safe display behavior.
- Added optional atomic Modbus FC16 display-only controller-status extension (holding registers 220–227); input measurement addresses unchanged.
- Added fault-code catalog, ADR-0005, and LCD fault-injection acceptance matrix.

## Firmware runtime decision — 2026-11-12
- Added ADR-0007 (proposed): C++ on Arduino-ESP32 (>= 3.0) with PlatformIO for both boards, framework-independent logic library tested on the host; MicroPython and ESPHome rejected (ESPHome on component-model fit, not Modbus server support).

## Permeate diversion decision — 2026-11-12
- Added ADR-0006 (proposed): permeate diversion is a normally closed quality-control dump valve on a tee drain branch, not a fail-to-drain safety function.
- Updated safety requirements, P&ID, acceptance tests, main-controller relay K3 description and AGENTS.md rule 3 to match; added permeate back-pressure requirement (highest line point about 5 ft above membrane).

## Stage A protocol tooling — 2026-11-11
- Added `ro_tools` host package: register-map validator, Python codec generator, simulated Modbus sensor node (TCP and serial RTU) with fault injection, pymodbus-based client, and `ro-tools` CLI.
- Added machine-readable enums, controller-flag bits, and fault codes to `protocol/register_map.yaml` (additive; protocol remains 1.1, no address/scale/signedness/access change).
- FC03 read-back of status registers 220–227 is permitted; status writes with inconsistent fault code/severity/count are rejected.
- Corrected `protocol/examples/sample_snapshot.json` protocol version to 1.1.
- Client verifies every reply against its request (function code, register count, FC16 echo, exception code) and raises `ProtocolError`; exception errors report the request's function code.
- Status-block safeguards: `ControllerStatus` has no defaults, `read_status()` returns `None` for a never-written block, the simulated bank exposes `last_status_sequence_progress_ms` (schema models `require_sequence_progress`), and the boot counter saturates and flags overflow on `reboot()`.
- Simulator logs each rejected request at WARNING with its reason (`bank.last_rejection`) and ignores requests with function code >= 0x80; added `ro-tools -v`.
- Schema hardening: duplicate YAML mapping keys and duplicate `critical_validity_bits` are rejected, Python keywords and unusable generated member names are rejected, wrong-typed values are reported as violations instead of `TypeError`, and generated masks use bitwise OR.
- Serial simulator: suppresses the echo of its own transmission and splits closely spaced RTU frames by request length instead of discarding the merged burst.

## Multi-node bus and RJ45 interconnect — 2026-11-13
- Protocol 1.2: added `node_type` (register 133) and `installed_mask` (register 134) for node identity on a multi-node bus. No existing address, scale, signedness or access changed; `validity_mask` must be a subset of `installed_mask`, and the simulator rejects a violation.
- Simulator: per-node profiles (`node_type`, `installed_mask`), a `Bus` that routes requests by unit id (1..15), and a `pressure_failed` preset (needs a pressure channel; rejected for tank nodes).
- `monitor` reference model: per-node health (OK, MISSING, WRONG_NODE, STALE, INVALID) and a production-permit check that fails closed. A backward or non-advancing sequence, a node reset not acknowledged by boot counter, a missing critical node, and an empty critical mask all deny production. A critical `NodeConfig` must require at least one validity bit.
- CLI: `ro-tools read --unit-id N` and `ro-tools sim --nodes TYPE:ID,...`.
- Interconnect: ADR-0008 (RJ45 24 V node bus, RS485 on the center pair, daisy chain, red cable and jacks, Ethernet hazard), pinout in `hardware/interconnect/pinout.yaml`, and `NODE_BUS_INTERCONNECT.md`. The pinout doc is checked against the YAML by a test.
- Optional pressure channel documented for every node. Not installed is not a fault; installed but implausible or lost is. The independent hardwired pressure cutoff remains mandatory.
- Hardware docs: main controller and power docs now state that the controller runs from the same 24 V supply as the node bus. Valve and contactor-coil rail voltage is TBD (12 V in the earlier plan). Termination, bias, trunk length, voltage drop, per-node current and transceiver choice remain TBD.

## 1-Wire input protocol — 2026-11-13
- Protocol 1.3: 1-Wire block 140-199, additive. Header (device count, bus status, scan generation, age) plus 8 slots of 7 words (64-bit ROM ID, primary, secondary, status); fault bit 10 `onewire_bus_fault`; polling window 100-199 (100 words). No existing address, scale, signedness or access changed; 1-Wire bits are not in validity or critical masks.

## 1-Wire hardware docs and ADR-0009 — 2026-11-13
- ADR-0009 (proposed): monitoring-only 1-Wire input, controller-side ROM-ID binding, single polling window 100-199; critical 1-Wire, a second poll block and paged access rejected.
- `pinout.yaml` `onewire:` section, `NODE_BUS_INTERCONNECT.md` 1-Wire section, sensor-node `HARDWARE_SPEC.md` front end and acceptance cases. Connector cavities, ratings, pull-up, GPIO, polyfuse and cable length are TBD. Checked by `test_interconnect_docs.py`.

## RO feed pressure transmitter and ADR-0010 — 2026-11-23
- ADR-0010 (proposed): Lefoo LFT2000 0-16 bar 2-wire 4-20 mA on the RO feed, loop powered from the 24 V trunk through an LM317 current limiter (about 29 mA) and PTC, 100 ohm sense resistor read directly by ESP32-S3 GPIO1 (ADC1_CH0) through 10 kohm, 100 nF and a BAT54S clamp. A shorted transmitter reads as overrange, not damage. Monitoring only; bit 6 stays non-critical; no software pressure trip. NE43 interpretation: 3.8-20.5 mA valid, outside sets `pressure_fault`.
- Same front end on every node; 4-20 mA is the only pressure signal. The solder jumper, the 0.5-4.5 V option and the tank node ADS1115 are removed.
- No protocol change: `pressure_raw_adc` keeps u16/counts and documents ESP32 12-bit counts. Full scale 232.1 psi fits `ro_feed_pressure_psi_x10`.
- Updated sensor-node hardware spec, Modbus spec, register reference, calibration and acceptance plan; checked by `test_pressure_docs.py`.

## 1-Wire device names, protocol 1.4 and ADR-0011 — 2026-11-23
- ADR-0011 (proposed): the owner names 1-Wire devices by ROM in `config/onewire_bindings.yaml`; the main controller sends each node the bound ROMs it reports as a display-only name table. Per-value entries, node-side NVS names and names in the input block rejected; controller firmware embedding deferred.
- Protocol 1.4, additive: holding 240-322 (83 registers, `write_multiple_only`, one FC16 write, FC03 read-back), `protocol/ONEWIRE_NAME_TABLE.md`. Invalid writes are rejected whole and the previous table is kept; RAM only; a 1.3 node answers ILLEGAL_DATA_ADDRESS. Names never affect validity, health or `production_permitted`. No existing address, scale, signedness or access changed.
- Owner decision (option A): column 20 of every LCD row on every page is reserved for a fault indicator: a space in normal operation, `*` while any WARNING or CRITICAL fault is active. Labels are 1-11 characters (`label_max_chars: 11`); 1-Wire rows are label + space + 7-character value + column 20. 1-Wire pages join NORMAL rotation after diagnostics and never preempt. Both LCD specs, LCD fault tests and the acceptance plan updated.
- Host tools: bindings validation, name-table codec and node-side validation (including all-zero ROM rejection), simulator support, reference LCD renderer with a column-20 indicator, `ro-tools onewire scan | validate | push` (`push` exits 4 for an unsupported node). Docs checked by `test_onewire_names_docs.py`.
- `protocol/examples/sample_snapshot.json` and the README `validate` example now say protocol 1.4.

## LCD texts fit columns 1-19 — 2026-11-23
- `STARTING / DATA WAIT` becomes `STARTING: DATA WAIT`.
- Row 4 of critical pages shows `RO: <text>` from a fixed per-state table (`START FLUSH`, `STOP FLUSH`, `MAINTENANCE`, ...) instead of raw enum names.
- Fault page header: `!! CRITICAL` / `! WARNING` with `n/m` right-aligned to column 19; counts above 99 show `99+`.
- Checked by `test_lcd_texts_docs.py`.

## Sensor-node carrier board and ADR-0012 — 2026-11-23
- ADR-0012 (proposed): an ESP32-S3-DevKitC-1-N16R8 on headers (owner decision 2026-11-24; the DevKitC-1-N8 is EOL). GPIO35-37 belong to the octal PSRAM.
  - GPIO map in `hardware/sensor-node/pinout.yaml`. It avoids strapping, USB, JTAG, UART0, octal-PSRAM and RGB-LED pins; GPIO1 stays pressure; buttons on GPIO10 and GPIO47.
  - Trunk input: MF-R065 PTC, MBRS3100, SMBJ33A, LMR36015 buck to 5 V, and the DevKitC SGM2212 for 3.3 V.
  - Per-node budget: 286.0 mA from 24 V, replacing the 200 mA assumption.
  - THVD1450 failsafe RS485 with SM712. Termination: controller cap on, far-end node J_TERM. Conditional controller bias values.
  - Universal pulse front end. DS2482-100 1-Wire master (0x18) with MF-R010 and TPD1E10B06.
  - ADS1115 at 0x48/0x49 with divider and clamp. HX711 with DVDD on 3.3 V (SparkFun board, SJ2 open). PCA9306 for the LCD.
  - BOM, and datasheets in `hardware/sensor-node/datasheets/`.
- Review fixes: a 120 ohm 3V3 bleeder sinks the worst-case 24 V fault injection (26.4 mA), because the DevKitC LDO cannot sink; 1 kohm series resistors on push-pull-driven pins that glitch at power-up (GPIO11, 13, 15, 16, 18); LMR36015 inductor 15 µH per Table 10-1.
- Corrected the 1-Wire ROM notation line in `NODE_BUS_INTERCONNECT.md`: the CLI prints wire order, family byte first and CRC last.
- HX711 excitation is 4.30 V AVDD, not 5 V.
- ADR-0008/0009 TBD lines, interconnect, power and controller wiring docs updated. Checked by `test_sensor_node_carrier_docs.py`. The 1-Wire guards in `test_interconnect_docs.py` now require ADR-0012 values instead of TBD for the closed keys.

## Sensor-node carrier reworked for the owner's ESP32-S3 board — 2026-11-25
- ADR-0012: the owner now uses a generic ESP32-S3 N16R8 board, DevKitC-1 pin-compatible (silkscreen ESP32-S3 2025-V1.4), instead of the DevKitC-1-N16R8. The DevKitC-1 user guide stays the pin-compatibility reference; the GPIO map is unchanged. Photos are in `hardware/sensor-node/reference/`.
- The board's regulator is a generic 1117-3.3, designed to AMS1117 maximums (1.3 V dropout at 0.8 A, θJA 90 °C/W). The old path (buck 5.0 V, 1N5819HW D2, possible on-board SL diode) gave 4.04 V against the 4.60 V needed. The buck is raised to 5.31 V nominal (RFBB 23.2 kΩ, 0.1 % resistors, 5.22-5.40 V). A first revision also replaced D2 with a TI LM66100 ideal diode (4.713 V, RON 120 mΩ max); see the owner decision below.
- Added C_3V3 (22 µF tantalum) for 1117 stability. Budget is now 305.6 mA from 24 V. The Wi-Fi-off rule stays (Wi-Fi TX gives TJ 141 °C at 50 °C ambient). EC modules, the LCD module and a 5 V flow meter must accept 5.40 V (owner facts).
- New Stage D items: RGB LED GPIO, 5Vin SL diode, SL orientation, IN-OUT/USB-OTG jumpers, 1117 temperature and dropout, 3V3 oscillation, `esptool` genuineness check.
- AMS1117 and LM66100 datasheets added. `test_sensor_node_carrier_docs.py` checks the 1117 limits and the dropout headroom.
- Owner decision (same day): D2 is deleted and no ideal diode replaces it; the buck feeds the board's 5Vin pin directly. With the buck still at 5.22-5.40 V and one on-board SL diode assumed, the 1117 input is 4.772 V (172 mV margin; 73 mV against the 1117's 3.399 V output maximum). Operating rule: connect USB only while the 24 V trunk is powered (recorded in ADR-0012, HARDWARE_SPEC and the acceptance plan). The LM66100 option is recorded as rejected.
- Bench (esptool v5.7.0 `flash-id`, COM port): ESP32-S3 (QFN56) v0.2, embedded PSRAM 8 MB AP_3v3 (not R8V; GPIO47/48 are 3.3 V), 16 MB flash (0x1C/0x7018), USB bridge WCH CH343. The genuine-module and bridge bench items are closed in ADR-0012.
- Bench note: static review of the board's factory flash dump (SHA-256 `cd0f30ac…273e`, kept outside the repo). It is Espressif's stock `led_strip` demo (IDF v4.4-dev, 2021), with no Wi-Fi, TCP/IP or Bluetooth stack linked, erased NVS and phy_init partitions, matching image hashes, and no data past the app. Recorded in ADR-0012 section 1.
