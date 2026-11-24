# LCD fault-priority acceptance matrix

| Case | Input | Expected |
|---|---|---|
| P01 | No active faults | Rotate normal pages |
| P02 | Advisory + warning | Warning first; advisory periodically |
| P03 | Warning + critical | Critical preempts within 250 ms if LCD responsive |
| P04 | Two critical faults | Oldest first, rotate equal priority, display count |
| P05 | Invalid flow while production known | Show invalid flow; controller decides shutdown |
| P06 | Invalid flow while standby known | Do not assert low-flow production fault |
| P07 | Controller block absent | `CTRL STATUS UNKNOWN`; no inferred pump state |
| P08 | Controller status stale >3 s | Mark remote state unknown; do not silently clear last fault |
| P09 | Unknown controller fault code | Show generic code |
| P10 | Sensor reading stale | `---` or `ERR`, never unlabeled last-good |
| P11 | LCD unplugged | Modbus and acquisition continue |
| P12 | Partial status write | Reject atomically; keep previous valid block |
| P13 | Sequence stuck | Detect stale publisher even if duplicate writes continue |
| P14 | Restart | `STARTING: DATA WAIT` until valid snapshots |
| P15 | String rendering | All rows exactly 20 columns: content in columns 1-19, column 20 is a space with no fault, `*` on every page (held or rotating) while any WARNING or CRITICAL fault is active, and a space with only ADVISORY faults |
| P16 | 1-Wire names pushed, then any fault | Fault order, severity and preemption identical to the same faults without names |
| P17 | 1-Wire pages present, no fault | 1-Wire pages appear in NORMAL rotation after diagnostics only |
| P18 | 1-Wire pages present, fault raised or 1-Wire bus fault | 1-Wire pages never preempt and never appear among fault pages; the bus fault shows as an ADVISORY |
| P19 | 1-Wire label of 11 characters, unnamed device | Label fits columns 1-11; unnamed shows `?FF-SSSS` (e.g. `?28-1BFF`) |
