# ADR-0011: 1-Wire device names (display-only name table)

**Status:** Proposed (2026-11-23) — pending owner review. Design basis: `docs/superpowers/specs/2026-11-23-onewire-device-names-design.md`. Builds on ADR-0009.

**Decision:** The owner names each 1-Wire device once, by ROM ID, in `config/onewire_bindings.yaml` (one file for the whole bus: `rom`, `role`, `label`). The main controller owns that table and sends each node the bound ROMs it currently reports as a **display-only name table**: protocol 1.3 to 1.4, additive, holding registers **240-322** (83 registers), written with one atomic FC16 write and readable with FC03 (`protocol/ONEWIRE_NAME_TABLE.md`). The node keeps the table in RAM only and uses it for nothing but rendering LCD labels. Names are **monitoring only**: they never touch `validity_mask`, `critical_validity_bits`, fault priority, node health or `production_permitted`. Labels are 1-11 LCD-safe characters.

**Owner decision (2026-11-23), option A: column 20 is reserved on every LCD page** for a fault/status indicator. A 1-Wire row is label (11, left-aligned) + space + 7-character right-aligned value + column 20; a DS2438's second row is 12 spaces + the 7-character mV value + column 20. The indicator glyph and any HOLD marker are not designed yet (`docs/TODO.md`). This is why the label limit is 11, not the 12 of the first draft. The wire keeps 6 label words, so the 12th byte is always NUL.

**Rationale:**
- ROM IDs are globally unique, so one bindings file covers every node and a device can move between nodes without renaming.
- The controller already binds roles by ROM (ADR-0009). A node never decides what a device is; it only shows the name it was given.
- Sending only the reported subset, sorted by ROM, fits one FC16 write (83 registers, limit 123) and takes about 100 ms at 19200 8E1. It is sent only on first contact or when `boot_counter`, `onewire_scan_generation` or the bindings revision changes, and is verified by read-back.
- **Why a write is allowed despite the no-writable-calibration rule.** `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md` section 7 forbids unguarded writable calibration over unauthenticated RS485, because a bad write could change what the node measures. The name table cannot: the node validates every write, rejects it whole if invalid, and uses it only to draw text. It is in the same category as the controller status block (220-227), which is also a display-only FC16 write. A forged or corrupt table can at worst show a wrong label, the same exposure the status block already accepts.
- No freshness timeout (unlike the status block): names are static. A reboot clears the table and the controller re-pushes it on the `boot_counter` change.

**Alternatives rejected:**
- **Per-value entries** (one entry per displayed value, so a DS2438 gets two): up to 16 entries exceed one FC16 write, which breaks the atomic full-block rule.
- **Node-side name storage in NVS** (names written once and kept by the node): two sources of truth that drift when a device moves or the bindings change, and a persistent writable store over RS485.
- **Names in the input block** (node reports names to the controller): wrong direction. The node does not own names; the controller does.
- **12-character labels with the value running to column 20:** superseded by option A, which keeps column 20 free on every page for the fault indicator.

**Consequences:**
- `ro-tools onewire scan | validate | push` and `NamePushPolicy` model the controller behavior. `push` exits 4 for an unsupported (1.3) node, 2 for a communication failure.
- A protocol 1.3 node answers ILLEGAL_DATA_ADDRESS; the controller marks it "names unsupported" until its `boot_counter` changes. Production is unaffected.
- On the LCD, 1-Wire pages join NORMAL rotation after the diagnostics page and never preempt or appear in fault pages. A 1-Wire bus fault stays an ADVISORY.
- LCD-safe characters assume the HD44780 A00 character ROM. The exact LCD is TBD; if it uses a different ROM, the safe set must be revisited.

**Deferred:** Main-controller firmware embedding of the bindings (a generated C++ table, same codegen pattern as the register map). It waits for the controller firmware tree (ADR-0007 TBDs); the host-tool model defines its behavior. Sensor-node firmware rendering also waits for the LCD hardware selection.
