# ESP32 RS485 / Modbus Sensor Acquisition Subsystem
**Specification:** SNS-MODBUS-001 · **Revision:** 0.1 · **Date:** 2026-11-10 · **Status:** implementation baseline, hardware TBD

## 1. Purpose and boundary
A dedicated ESP32 sensor node acquires water quality, flow, temperature, pressure, and atmospheric tank weight measurements. It exposes a **read-only measurement interface** and a narrowly controlled calibration/configuration interface via Modbus RTU over two-wire half-duplex RS485. It never controls a pump, concentrate flush valve, or permeate diversion valve. The main industrial ESP32-S3 remains the sole software decision-maker.

Independent hardwired high-pressure, high-level, and distribution-pump low-water protection remain outside the Modbus dependency chain.

## 2. Instrumentation
| Signal | Count | Interface | Notes |
|---|---:|---|---|
| Feed conductivity (EC) | 1 | conditioned analog or digital | temperature compensated; low-cost EC modules need calibration |
| Permeate conductivity (EC) | 1 | conditioned analog or digital | choose range suitable for low EC |
| Permeate flow | 1 | pulse counter | upstream of permeate diversion; counts gross membrane output |
| Concentrate flow | 1 | pulse counter | downstream of normal needle + flush bypass recombination |
| Permeate temperature | 1 | meter-integrated, interface TBD | no assumption that sensor is DS18B20 |
| Concentrate temperature | 1 | meter-integrated, interface TBD | may serve as feed-temperature proxy only if validated |
| Tank load cells | 2 | two HX711 | rear-hinged platform; empirical gallons calibration |
| RO feed pressure | 1 proposed | analog transducer | diagnostic only; hardwired cutoff independent |

Feed EC temperature compensation needs a defensible temperature measurement. A dedicated feed temperature probe may be required; do not silently use permeate temperature without testing. Add channel if selected. Additional pressure channels are optional expansion.

## 3. Physical layer
- Modbus RTU server unit ID **1**; main controller is client/master.
- Default **19200 baud, 8 data bits, even parity, 1 stop bit (8E1)**; configurable only with coordinated client change.
- Two-wire half-duplex RS485, 3.3 V UART-to-transceiver interface, DE/RE control as required.
- Use one 120-ohm termination at each physical bus end; bias at **one** appropriate location, not every node. For two-node short cable, document installed termination and bias values after inspecting controller internals.
- Prefer isolated transceiver on sensor node if practical; confirm main board isolation. Include signal reference conductor as appropriate to isolation design, shielding/earth policy, ESD/transient protection, and separated routing from motor wiring.
- Do not assume RS485 A/B nomenclature is consistent between manufacturers: verify polarity with documentation/test.
- Implement RTU frame timing according to serial configuration, CRC16, and response timeouts. Only one client polls the bus.

## 4. Register model and addressing
`protocol/register_map.yaml` is normative. Addresses are **zero-based PDU offsets**; never add 30001/40001 to wire addresses. Read-only live values are **input registers** (function 04). Controlled configuration lives in **holding registers** (function 03), with writes disabled by default until an authenticated/local physical maintenance mode is implemented; Modbus RTU itself has no authentication.

- All registers are 16-bit, big-endian within each register (Modbus convention).
- 32-bit unsigned counters use **high word first**, then low word.
- Signed 16-bit fields use two's-complement.
- Most measurements use scaled integers. Exact scale, signedness, units, and ranges appear in YAML.
- Do not use magic sentinel values to imply valid data. Use validity bits plus explicit freshness and update counters. When invalid, raw measurement may be zero or last value but MUST NOT be trusted by client.
- A single function-04 read of 100..139 is a coherent, atomic published snapshot; node double-buffers acquisitions and copies a snapshot for the response. Any later expansion must preserve this behavior.
- The register block includes protocol version, snapshot counter, age, validity, and diagnostics so the client can reject stale/incomplete data.
- Unsigned flow/volume overflow is saturated and flagged, never wrapped silently.

## 5. Polling and acquisition
- Main controller polls input registers 100..139 every **1 second** (configurable).
- Sensor acquisition tasks run independently: pulse counts continuously, flow rate ~1 s rolling window, load cells ~5–10 Hz if hardware permits, pressure ~5–10 Hz, temperature and conductivity ~1–5 s.
- Each channel carries last-good sample time internally. Publish age of oldest **required critical** channel in milliseconds, saturated at 65535.
- Publish snapshot sequence monotonically modulo 65536, advancing only on newly committed acquisition snapshots. Repeated identical counters across excessive polls are stale.
- Client accepts snapshot only if protocol major version compatible, status operational, configured critical validity bits set, critical age <= 3000 ms, and communication is healthy.
- Main controller shuts down RO production if no acceptable snapshot arrives within **3 seconds**. These are initial software defaults to validate, not substitutes for hardwired protections.

## 6. Required calculations and ownership
Node reports sensor measurements and diagnostics. Main controller computes:
- `feed_flow_gpm = permeate_gpm + concentrate_gpm` when both valid and all membrane outlets accounted for.
- `recovery_pct = 100 * permeate / (permeate + concentrate)` when denominator > 0 and production state valid.
- `rejection_pct = 100 * (1 - permeate_EC / feed_EC)` when both conductivity channels valid, comparable, temperature-normalized, and feed_EC > 0.
- Net stored gallons from empirical rear-hinge/front-load-cell calibration; calibration may execute on sensor node, but tank thresholds and decisions belong to main controller.

Flow calibration must support pulses per gallon independently per meter; do not infer values from generic meter listings. Persist pulse totals across restart with wear-conscious periodic checkpoints; provide boot epoch/uptime so client detects resets and counter discontinuities.

## 7. Calibration and persistence
- Persist per-channel calibration (coefficients, units, calibration timestamp if RTC available, revision, CRC/checksum) using wear-aware nonvolatile storage.
- Default uncalibrated channels to invalid, not an invented engineering-unit reading.
- EC: support two-point calibration where hardware allows, with temperature compensation to 25°C and documented compensation model. Keep raw EC and corrected EC distinguishable internally.
- Flow: independently calibrate pulse/gallon with measured volumes; include zero-flow timeout and noise rejection.
- Load cells: individual tare and gain, combined empirical tank-volume calibration over known fill increments, fill/drain hysteresis check, mechanical-stop/hinge considerations.
- Pressure: offset/span against trusted gauge, verify transducer supply and signal range.
- Configuration writes: initial release read-only from Modbus; use local USB maintenance command/tool for calibration until explicit protected write protocol and test plan exist. Never expose unguarded writable calibration over unauthenticated RS485.

## 8. Fault model
Status flags cover sensor missing, uncalibrated, out-of-range, ADC fault, HX711 timeout, pulse counter fault, EC saturation, stale measurement, nonvolatile config failure, and internal watchdog reset. Individual validity bits map to critical channels. Missing flow pulses can mean genuine zero flow or a failed sensor: the main controller treats zero concentrate flow during production as unsafe; it cannot infer hardware health from pulse absence alone.

A CRC-valid RTU response is not proof of sensor validity. Do not use Modbus alone as a safety interlock. All mains motor safety wiring must be independently verified.

## 9. Firmware architecture
Sensor firmware modules: `main`, `drivers/{flow,temperature,ec,pressure,hx711,rs485}`, `services/{acquisition,snapshot,calibration,health}`, `protocol/{modbus_server,register_codec}`, `storage/config_store`, `tests`.

Use fixed-size buffers where practical, deterministic scheduling, watchdog with safe restart, bounded memory use, and explicit error states. Keep transport, sensor drivers, calibration, and register serialization independently testable.

## 10. Bench acceptance
1. Read unit ID 1 and version via function 04; check all addresses, scaling, and word order.
2. Reject illegal addresses/function codes and malformed CRC; no reboot or memory corruption.
3. Verify simultaneous snapshot consistency while sensor values change.
4. Disconnect RS485 and confirm main controller inhibits pump within timeout.
5. Disconnect each critical sensor and confirm validity clears and main controller inhibits production.
6. Power-cycle node and verify calibration CRC handling and no fabricated data.
7. Inject high pulse rate, pulse dropout, ADC saturation, HX711 missing, and wraparound counters.
8. Verify independent pump high-pressure and high-level interlocks with ESP32 disconnected.
9. Test with simulated sensors and dummy loads before connecting live equipment.

## 11. Unresolved hardware selections
Exact sensor node ESP32 variant; controller pinout; RS485 transceiver/isolation; EC front ends; external ADC; flow-meter pulse electrical output and pressure ratings; temperature sensor type; pressure transducer range; power budget; enclosure; grounding. These are gates, not permission to guess.

## Node identity and multi-node bus (protocol 1.2)
Two read-only input registers identify the node: register 133 `node_type` (0 ro_skid, 1 tank) and register 134 `installed_mask` (same bit positions as `validity_mask`; a set bit means that sensor is physically fitted). Invariant: `validity_mask` is a subset of `installed_mask`; a fitted-but-failing sensor has its installed bit set and its validity bit clear. Registers 135-139 remain reserved.

Unit ids 1-15 are set by a 4-position DIP switch on the carrier board, read at boot. A duplicate or out-of-range id leaves the node silent on the bus.
