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
| P14 | Restart | `STARTING / DATA WAIT` until valid snapshots |
| P15 | String rendering | All rows <=20 characters |
