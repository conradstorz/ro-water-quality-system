# Main controller → sensor node 1-Wire name table (protocol 1.4)

This holding-register block carries *display-only* names for the 1-Wire devices a node reports. The node only renders the labels on its optional LCD. It is not a control plane: the node never uses the table for validity, fault priority, node health, `production_permitted`, or any actuator. Decision: `docs/decisions/ADR-0011-onewire-device-names.md`. Design: `docs/superpowers/specs/2026-11-23-onewire-device-names-design.md`. `register_map.yaml` (`onewire_name_table`) is normative; `host_tools/tests/test_docs_consistency.py` fails if the table below drifts from it.

## Write contract
- Function code **16 (0x10)**, all **83 registers 240–322 in one transaction** (`write_mode: atomic_full_block_only`). The node rejects any write that does not cover exactly 240–322.
- FC03 read-back of 240–322 is allowed. After boot the table reads all zero (empty).
- The node validates the whole block and, on any violation, replies ILLEGAL_DATA_VALUE and **keeps the previous table**:
  - `names_schema_major` ≠ 1;
  - `names_entry_count` > 8;
  - for each used entry (n < count): an all-zero ROM, a ROM whose Dallas CRC-8 fails, an empty label, a label longer than 11 characters (the 12th label byte, the low byte of `label5`, must be NUL), a label byte outside the LCD-safe set, or a NUL followed by a non-NUL;
  - the same ROM in two used entries;
  - any non-zero word in an unused entry (n ≥ count).
- Storage is RAM only. The table is empty after node boot; the controller re-pushes it. Unlike the status block (220–227) it has no freshness timeout: names are static.
- A protocol 1.3 node answers ILLEGAL_DATA_ADDRESS. The controller marks it "names unsupported" until its `boot_counter` changes. This never affects production.

## Encoding
- Header: 240 `names_schema_major` (1), 241 `names_revision` (opaque u16; the controller uses CRC-16/MODBUS of `config/onewire_bindings.yaml`), 242 `names_entry_count` (0–8).
- Entry n (0–7) starts at 243 + 10n: `rom0..rom3` with the same 64-bit ROM encoding as input slots `onewire_sN_rom0..3` (high word first; family code = low byte of `rom3`; CRC-8 = high byte of `rom0`), then `label0..label5`.
- Label: ASCII, 2 characters per word, high byte first, NUL-padded, no embedded NUL, 1–11 characters (`label_max_chars: 11`). Six words are kept on the wire, so the last byte is always NUL.
- LCD-safe characters: 0x20–0x7D except 0x5C (`\`) and 0x7E (`~`). This assumes the common HD44780 A00 character ROM (the exact LCD is TBD), where 0x5C renders as ¥ and 0x7E as an arrow.
- Entries are sorted by ROM ascending; the controller sends only the bound ROMs the node currently reports (at most 8).
- Example: ROM text `28FF1B2C3D5F4EDE` (family 0x28 first, CRC 0xDE last) is the integer 0xDE4E5F3D2C1BFF28 and is written as `rom0..rom3` = 0xDE4E, 0x5F3D, 0x2C1B, 0xFF28.

## Holding registers (zero-based PDU addresses)
| Address | Name | Encoding |
|---|---|---|
| 240 | names_schema_major | u16, equals 1 |
| 241 | names_revision | u16, opaque to the node |
| 242 | names_entry_count | u16, 0-8 |
| 243 | names_e0_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 244 | names_e0_rom1 | u16, ROM word 1 |
| 245 | names_e0_rom2 | u16, ROM word 2 |
| 246 | names_e0_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 247 | names_e0_label0 | u16, label chars 1-2 (high byte first) |
| 248 | names_e0_label1 | u16, label chars 3-4 (high byte first) |
| 249 | names_e0_label2 | u16, label chars 5-6 (high byte first) |
| 250 | names_e0_label3 | u16, label chars 7-8 (high byte first) |
| 251 | names_e0_label4 | u16, label chars 9-10 (high byte first) |
| 252 | names_e0_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 253 | names_e1_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 254 | names_e1_rom1 | u16, ROM word 1 |
| 255 | names_e1_rom2 | u16, ROM word 2 |
| 256 | names_e1_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 257 | names_e1_label0 | u16, label chars 1-2 (high byte first) |
| 258 | names_e1_label1 | u16, label chars 3-4 (high byte first) |
| 259 | names_e1_label2 | u16, label chars 5-6 (high byte first) |
| 260 | names_e1_label3 | u16, label chars 7-8 (high byte first) |
| 261 | names_e1_label4 | u16, label chars 9-10 (high byte first) |
| 262 | names_e1_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 263 | names_e2_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 264 | names_e2_rom1 | u16, ROM word 1 |
| 265 | names_e2_rom2 | u16, ROM word 2 |
| 266 | names_e2_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 267 | names_e2_label0 | u16, label chars 1-2 (high byte first) |
| 268 | names_e2_label1 | u16, label chars 3-4 (high byte first) |
| 269 | names_e2_label2 | u16, label chars 5-6 (high byte first) |
| 270 | names_e2_label3 | u16, label chars 7-8 (high byte first) |
| 271 | names_e2_label4 | u16, label chars 9-10 (high byte first) |
| 272 | names_e2_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 273 | names_e3_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 274 | names_e3_rom1 | u16, ROM word 1 |
| 275 | names_e3_rom2 | u16, ROM word 2 |
| 276 | names_e3_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 277 | names_e3_label0 | u16, label chars 1-2 (high byte first) |
| 278 | names_e3_label1 | u16, label chars 3-4 (high byte first) |
| 279 | names_e3_label2 | u16, label chars 5-6 (high byte first) |
| 280 | names_e3_label3 | u16, label chars 7-8 (high byte first) |
| 281 | names_e3_label4 | u16, label chars 9-10 (high byte first) |
| 282 | names_e3_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 283 | names_e4_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 284 | names_e4_rom1 | u16, ROM word 1 |
| 285 | names_e4_rom2 | u16, ROM word 2 |
| 286 | names_e4_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 287 | names_e4_label0 | u16, label chars 1-2 (high byte first) |
| 288 | names_e4_label1 | u16, label chars 3-4 (high byte first) |
| 289 | names_e4_label2 | u16, label chars 5-6 (high byte first) |
| 290 | names_e4_label3 | u16, label chars 7-8 (high byte first) |
| 291 | names_e4_label4 | u16, label chars 9-10 (high byte first) |
| 292 | names_e4_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 293 | names_e5_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 294 | names_e5_rom1 | u16, ROM word 1 |
| 295 | names_e5_rom2 | u16, ROM word 2 |
| 296 | names_e5_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 297 | names_e5_label0 | u16, label chars 1-2 (high byte first) |
| 298 | names_e5_label1 | u16, label chars 3-4 (high byte first) |
| 299 | names_e5_label2 | u16, label chars 5-6 (high byte first) |
| 300 | names_e5_label3 | u16, label chars 7-8 (high byte first) |
| 301 | names_e5_label4 | u16, label chars 9-10 (high byte first) |
| 302 | names_e5_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 303 | names_e6_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 304 | names_e6_rom1 | u16, ROM word 1 |
| 305 | names_e6_rom2 | u16, ROM word 2 |
| 306 | names_e6_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 307 | names_e6_label0 | u16, label chars 1-2 (high byte first) |
| 308 | names_e6_label1 | u16, label chars 3-4 (high byte first) |
| 309 | names_e6_label2 | u16, label chars 5-6 (high byte first) |
| 310 | names_e6_label3 | u16, label chars 7-8 (high byte first) |
| 311 | names_e6_label4 | u16, label chars 9-10 (high byte first) |
| 312 | names_e6_label5 | u16, label char 11 (high byte); low byte must be NUL |
| 313 | names_e7_rom0 | u16, ROM word 0 (bits 63-48, CRC byte high) |
| 314 | names_e7_rom1 | u16, ROM word 1 |
| 315 | names_e7_rom2 | u16, ROM word 2 |
| 316 | names_e7_rom3 | u16, ROM word 3 (bits 15-0, family code = low byte) |
| 317 | names_e7_label0 | u16, label chars 1-2 (high byte first) |
| 318 | names_e7_label1 | u16, label chars 3-4 (high byte first) |
| 319 | names_e7_label2 | u16, label chars 5-6 (high byte first) |
| 320 | names_e7_label3 | u16, label chars 7-8 (high byte first) |
| 321 | names_e7_label4 | u16, label chars 9-10 (high byte first) |
| 322 | names_e7_label5 | u16, label char 11 (high byte); low byte must be NUL |
