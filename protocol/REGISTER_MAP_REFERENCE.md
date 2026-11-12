# Register map quick reference
Normative machine-readable map: `register_map.yaml`.

- Input registers (function 04), zero-based PDU offset **100–139**, read 40 words atomically.
- Holding registers (function 03), offsets **200–202**, read-only metadata; writes not implemented.
- For a field named `_x10`, raw integer / 10 gives engineering units. Similar for `_x100`, `_x1000`.
- `u32` and `i32` occupy 2 words, high word first; signed integers use two's complement.
- `validity_mask` bits 0..9 describe channels; bit 10 is optional feed temperature. Required critical bits are 0,1,2,3,7. Pressure validity bit 6 is optional until a pressure transducer is installed; the independent hardwired pressure cutoff is mandatory regardless. Do not mark an absent pressure sensor valid.
- Reserved fields return zero and must be ignored by clients.
- A status bit of operational alone is not enough; verify critical validity, freshness, and update sequence.
- Do not infer pump protection from software pressure readings.
