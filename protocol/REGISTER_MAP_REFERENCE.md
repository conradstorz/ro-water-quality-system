# Register map quick reference
Normative machine-readable map: `register_map.yaml`.

- Input registers (function 04), zero-based PDU offset **100–199**, read 100 words atomically (protocol 1.3; 1.2 was 100–139, 40 words).
- Holding registers (function 03), offsets **200–202**, read-only metadata; writes not implemented.
- For a field named `_x10`, raw integer / 10 gives engineering units. Similar for `_x100`, `_x1000`.
- `u32` and `i32` occupy 2 words, high word first; signed integers use two's complement.
- `validity_mask` bits 0..9 describe channels; bit 10 is optional feed temperature. Required critical bits are 0,1,2,3,7. On a multi-node bus these bits are spread across nodes (bits 0-3 on the RO skid, bit 7 on the tank), so the controller must cover all of them through its configured critical nodes. Pressure validity bit 6 is optional until a pressure transducer is installed; the independent hardwired pressure cutoff is mandatory regardless. Do not mark an absent pressure sensor valid.
- Reserved fields return zero and must be ignored by clients.
- Node identity (protocol 1.2): register 133 node_type (0 ro_skid, 1 tank) and 134 installed_mask (same bit positions as validity_mask; set = sensor physically fitted). validity_mask must be a subset of installed_mask. Fitted-but-failing = installed bit set, validity bit clear. Registers 135-139 remain reserved.
- A status bit of operational alone is not enough; verify critical validity, freshness, and update sequence.
- Do not infer pump protection from software pressure readings.
- 1-Wire input (protocol 1.3, additive, monitoring only): 140 `onewire_device_count`; 141 `onewire_bus_status` (bit0 bus_short, 1 no_presence, 2 crc_errors, 3 overflow); 142 `onewire_scan_generation`; 143 `onewire_age_ms` (saturates 65535). Eight slots of 7 words from 144 (slot n base = 144 + 7n): `rom0..rom3` (64-bit ROM ID, high word first, family code = low byte of rom3), `primary` (i16), `secondary` (i16), `status` (bit0 present, 1 valid, 2 stale, 3 crc_error, 4 unsupported_family, 5 missing). Family 0x28 DS18B20 primary = degC x100; 0x26 DS2438 primary = degC x100, secondary = mV; other families report ROM ID only with zero values and `valid` clear. Slots sorted by ROM ID ascending; more than 8 devices report the 8 lowest and set bus_status bit 3. Fault bit 10 `onewire_bus_fault`. 1-Wire bits are never part of `validity_mask` or the critical set and never affect production permission.
