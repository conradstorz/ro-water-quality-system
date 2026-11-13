# 1-Wire input for sensor nodes — design

Date: 2026-11-13. Status: draft for review. Builds on `2026-11-13-sensor-node-interconnect-design.md` (protocol 1.2).

## 1. Scope
Add a 1-Wire bus input to every sensor node (same carrier board, populated or not). Multiple 1-Wire devices daisy-chain on one bus. Devices may be of mixed families (e.g. DS18B20 temperature, DS2438 battery/humidity monitor). Monitoring only: 1-Wire data never permits or inhibits RO production. Any interlock stays hardwired.

## 2. Hardware
- **Connector:** Nilight 3-pin waterproof male/female wire harness connector (10-pack, automotive quick-disconnect). It is an inline wire-to-wire connector, not a panel mount. Each node has a short pigtail through a cable gland; the chain joins at plug/socket pairs. Each node carries one male-end and one female-end pigtail so the chain runs in one direction. Label every plug "1-WIRE".
- **Pinout:** the connector has no standard pin assignment. Signals are +5 V, DATA, GND; cavity numbering is **TBD** until confirmed against the actual part. Generic 3-pin automotive plugs mate with each other, so 1-WIRE plugs must be labeled and kept away from the 24 V trunk and RS485 wiring.
- **Connector ratings:** voltage and current rating **TBD** (confirm from the listing/datasheet).
- **Power:** normal (non-parasitic) power from the node 5 V rail through a polyfuse. Fuse rating TBD.
- **Bus driver:** ESP32 GPIO, series resistor, pull-up to 3.3 V (value TBD, depends on cable length), ESD/TVS protection on DATA. GPIO **TBD**.
- **Topology:** linear daisy-chain or short stubs. Maximum cable length and device count **TBD** (measure in Stage D). Cable shield, if used, is bonded at the node end only.

## 3. Protocol 1.3 (additive)
No existing address, scale, signedness or write permission changes (AGENTS.md rule 2). Version 1.2 to 1.3.

A second input poll block, registers 140-199 (60 words), is polled with the existing 100-139 block. Reserved words 135-139 are unchanged.

| Address | Name | Type | Notes |
|---|---|---|---|
| 140 | `onewire_device_count` | u16 | Devices currently present |
| 141 | `onewire_bus_status` | u16 bitmask | bit 0 bus_short, 1 no_presence, 2 crc_errors, 3 overflow (more than 8 devices found) |
| 142 | `onewire_scan_generation` | u16 | Increments (mod 2^16) whenever the set of devices changes |
| 143 | `onewire_age_ms` | u16 | Age of the 1-Wire data at read time; saturates at 65535 |
| 144-199 | 8 slots x 7 words | | Slot n starts at 144 + 7n |

Slot layout (7 words):

| Offset | Content | Type |
|---|---|---|
| +0..+3 | 64-bit ROM ID, big-endian, high word first; family code is the low byte of the ID | 4 x u16 |
| +4 | primary value | i16 |
| +5 | secondary value | i16 |
| +6 | slot status bitmask | u16 |

Slot status bits: 0 present, 1 valid, 2 stale, 3 crc_error, 4 unsupported_family, 5 missing.

Rules:
- Slots are sorted by ROM ID ascending. A device that disappears stays in its slot marked `missing` (present clear) so the controller can tell lost from never-present. An empty slot is all zero words.
- Value meaning depends on family: DS18B20 (0x28) primary = degC x100. DS2438 (0x26) primary = degC x100, secondary = mV. Any other family: `unsupported_family`, ROM ID only, value words zero and `valid` clear. No value is ever guessed or substituted.
- A value is meaningful only when `valid` is set and `stale`, `crc_error`, `missing` are clear.
- More than 8 devices: the 8 lowest ROM IDs are reported and `bus_status` bit 3 is set.
- New fault bit 10 `onewire_bus_fault` (monitoring only).
- 1-Wire bits are never added to `validity_mask` or `critical_validity_bits`.
- Polling gains a second block: `input_start 140`, `input_count 60`.

## 4. Controller side
The controller's own config binds ROM IDs to roles (e.g. "feed temperature"); a node's self-report never defines a role. Unbound devices are logged and displayed only. `monitor.py` gains `OneWireHealth` and `evaluate_onewire`, which are kept separate from `evaluate` and `production_permitted`: `production_permitted` results are identical with and without 1-Wire faults.

## 5. Firmware (Stage B, not started)
`OneWireBus` interface with a mock. Boot-time ROM search, then rescan at an interval that is TBD. DS18B20 conversion is asynchronous so the 750 ms wait never blocks the Modbus responder. ROM and scratchpad CRCs are checked. The 140-199 block belongs to the same coherent snapshot; `onewire_age_ms` is computed at read time.

## 6. Host tools and tests
- `register_map.yaml` 1.3, regenerated codec (`generate --check` current).
- `sim/register_bank.py`: `OneWireDevice` model and slot table. `sim/presets.py`: 1-Wire presets.
- CLI `read` prints the 1-Wire table.
- Tests: 1.3 addresses and scaling with 1.2 addresses unchanged; slot ordering; lost, duplicate-ROM, overflow, CRC-error and stale cases; unsupported family; no 1-Wire bit in `critical_validity_bits`; production decisions unchanged by 1-Wire faults; pinout doc test extended.

## 7. Docs
`hardware/interconnect/pinout.yaml` and `NODE_BUS_INTERCONNECT.md` (1-Wire section), `hardware/sensor-node/HARDWARE_SPEC.md`, the Modbus spec, `REGISTER_MAP_REFERENCE`, `CHANGELOG.md`, new `docs/decisions/ADR-0009-onewire-monitoring-input.md` (Proposed).

## 8. Open TBDs (not guessed)
Nilight plug cavity numbering, voltage/current rating; pull-up value; maximum cable length and device count; GPIO; rescan interval; polyfuse rating; supported DS2438 variants and other families.
