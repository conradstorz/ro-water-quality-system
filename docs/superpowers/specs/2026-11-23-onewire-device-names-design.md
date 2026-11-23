# 1-Wire device names — design

Status: draft for owner approval (2026-11-23). Builds on ADR-0009 and `2026-11-13-onewire-input-design.md`.

## Goal
Every 1-Wire device has a unique 64-bit ROM ID. The owner names each device once ("Outside temp", "Storage tank") and the name appears in host tools/logs, in the main controller, and on the optional sensor-node LCD next to the device's reading.

## Unchanged principles (ADR-0009)
- The main controller owns the ROM-to-name table. A node never decides what a device is; it only displays a name it was given.
- 1-Wire stays monitoring only. Names never affect validity, critical masks, fault priority or `production_permitted`.

## 1. Bindings file (source of truth)
`config/onewire_bindings.yaml`, one file for the whole bus (ROM IDs are globally unique, so no node number is needed and a device can move between nodes):

```yaml
schema: 1
devices:
  - rom: 28FF4A1B2C3D4E5F    # 16 hex digits, family byte first, CRC byte last (wire order)
    role: outside_temp       # snake_case identifier for code and logs; unique
    label: Outside temp      # LCD/display text; unique
```

Validation (host tool, fails the build/CLI on any violation):
- `rom`: exactly 16 hex digits (case-insensitive), Dallas CRC-8 correct, family known or not (unknown families can be named; the node shows the ROM only, with no value). Unique.
- `role`: `^[a-z][a-z0-9_]{0,31}$`, unique.
- `label`: 1-12 characters from the LCD-safe set (below), no leading/trailing space, unique.
- ROM text format is defined once in `onewire.py` (`format_rom` / `parse_rom`) next to `make_rom`, and maps to the same 64-bit integer the input slots carry.

## 2. Commissioning workflow
1. Plug in the new device.
2. `ro-tools onewire scan --unit-id N`: lists every slot on the node: ROM text, family, current reading(s), and the bound role/label, or `UNBOUND` with a ready-to-paste YAML stub.
3. Paste the stub into `config/onewire_bindings.yaml`, fill in `role` and `label`.
4. `ro-tools onewire validate` checks the file.
5. `ro-tools onewire push --unit-id N` writes that node's name table (section 4) and reads it back. In production the main controller does this automatically.

## 3. LCD layout (20 × 4, HD44780)
Row arithmetic: label 12 + space 1 + value 7 = 20.
- Value field is 7 characters, right-aligned. Temperature (DS18B20, DS2438 primary): one decimal plus `C`, e.g. `  21.5C`, ` -12.3C`, ` 125.0C`. DS2438 voltage (secondary): ` 3300mV`. A value that cannot fit in 7 characters shows `    ERR`. Invalid or stale shows `    ---`.
- Plain `C` (no degree glyph) keeps output independent of the LCD character ROM.
- A DS18B20 takes one row. A DS2438 takes two rows: `label + temperature`, then 13 spaces + mV.
- An unnamed device shows `?` + family + `-` + low 16 bits of the serial as its label, e.g. `?28-4E5F`.
- 1-Wire pages join NORMAL rotation after the diagnostics page, 4 rows per page, as many pages as the devices need (at most 4 for 8 DS2438s). They never preempt and never appear in fault pages. A 1-Wire bus fault remains an ADVISORY as today.
- LCD-safe label characters: printable ASCII 0x20-0x7D except `\` (0x5C) and `~` (0x7E). This assumes the common HD44780 A00 character ROM (the exact LCD is TBD), where 0x5C renders as ¥ and 0x7E as an arrow.

## 4. Protocol 1.4: name table (holding registers 240-322)
Additive minor version (1.3 → 1.4). No existing address, scale, signedness or access changes.

| Address | Name | Encoding |
|---|---|---|
| 240 | `names_schema_major` | u16, equals 1 |
| 241 | `names_revision` | u16, opaque to the node (controller uses CRC-16 of the bindings file) |
| 242 | `names_entry_count` | u16, 0-8 |
| 243 + 10n .. 252 + 10n | entry n (n = 0..7) | `rom0..rom3` (same 4-word ROM encoding as input slots), then `label` in 6 words |

- Label encoding: ASCII, 2 characters per word, high byte first, NUL-padded at the end, no embedded NUL. 12 characters maximum.
- Write: FC16, all 83 registers 240-322 in one transaction, like the status block (220-227). The node rejects partial writes and any write where `names_schema_major != 1`, `names_entry_count > 8`, a used entry has a bad ROM CRC, a label outside the LCD-safe set, an empty label, or an embedded NUL, a ROM appears twice, or an unused entry is not all zero. It replies ILLEGAL_DATA_VALUE and keeps the previous table.
- FC03 read-back of 240-322 is allowed.
- Storage: RAM only. The table is empty after node boot. Display-only, like the status block. Unlike the status block it has no freshness timeout: names are static.
- Why a write is allowed: the Modbus spec forbids writable calibration over RS485. The name table is display-only, in the same category as the controller status block, and the node never uses it for anything but rendering.
- Size: 83 registers (FC16 limit is 123); about 100 ms on the wire at 19200 8E1, sent only on change.

## 5. Controller behavior (modelled in host tools; firmware deferred)
- Per node, send only the bindings whose ROM the node currently reports, at most 8 since a node has 8 slots, sorted by ROM.
- Push when: first contact, `boot_counter` changes, `onewire_scan_generation` changes, or the bindings revision changes. Verify with FC03 read-back.
- A protocol 1.3 node answers ILLEGAL_ADDRESS: mark the node "names unsupported" and do not retry until its `boot_counter` changes.
- Isolation invariant (tested): a rejected, failed or unsupported name write never changes node health or `production_permitted`.

## 6. Host tooling changes
- `onewire.py`: `format_rom`, `parse_rom`.
- New `onewire_names.py`: load/validate the bindings file, encode/decode the 83-word table, per-node subset selection, and a reference LCD row renderer (proves every row fits 20 columns).
- `monitor.py`: `OneWireBinding` gains `label`.
- `schema.py` / `register_map.yaml`: new `onewire_name_table` section beside `controller_status_extension`, with a no-overlap check. Codegen updated.
- Simulator register bank, server and client: accept, validate and read back the table. New preset with named devices.
- CLI: `ro-tools onewire scan | validate | push`.

## 7. Docs
ADR-0011 (Proposed), new `protocol/ONEWIRE_NAME_TABLE.md`, `REGISTER_MAP_REFERENCE.md`, Modbus spec, both LCD specs, `LCD_FAULT_PRIORITY_TESTS.md`, acceptance plan, CHANGELOG. `test_status_extension_table_matches_yaml` gets scoped to the 220-227 block.

## Deferred
Main-controller firmware embedding of the bindings (a generated C++ table, same codegen pattern as the register map). It waits for the controller firmware tree (ADR-0007 TBDs); the host-tool model above defines its behavior.
