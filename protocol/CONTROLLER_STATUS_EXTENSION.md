# Main controller → sensor node status extension (v1.1 draft)

This **optional** Modbus holding-register block carries *display-only* main-controller status. It is not a control plane. The sensor node shall never treat these values as authority to run pumps, move valves, clear alarms, or override independent protection.

## Atomic write contract
- Main controller is sole authorized writer in intended physical topology; Modbus RTU has no authentication. Protect physical access and avoid untrusted masters.
- Use function code **16 (0x10), Write Multiple Holding Registers**, to write **all 8 registers 220–227 in one transaction**. Reject individual/partial writes, unsupported values, and writes to 200–202. Do not publish any field until all values validate. On invalid write, preserve prior snapshot and return a Modbus exception.
- The sensor node maintains `last_valid_status_received_ms` locally; **never trust remote uptime as a freshness clock**. Treat the block as stale after 3000 ms without a valid write. `sequence` increments modulo 65536 on each main-controller publish; duplicates can be accepted but must not indefinitely mask a stuck publisher (require progress within timeout or mark stale).
- A write is only display context. On expiry, state and pump status are UNKNOWN. A previously observed controller-latched fault must not be shown as resolved merely because the status timed out.

## Holding registers (zero-based PDU addresses)
| Address | Name | Encoding |
|---|---|---|
| 220 | status_schema_major | u16, 1 |
| 221 | status_sequence | u16, wraps |
| 222 | ro_state | u16 enum below |
| 223 | pump_commanded | u16: 0=off, 1=on, 2=unknown (command, **not proof of motor state**) |
| 224 | controller_fault_code | u16: 0=no active fault, otherwise code from `docs/specs/FAULT_CODE_CATALOG.md` |
| 225 | controller_fault_severity | u16: 0=none, 1=advisory, 2=warning, 3=critical |
| 226 | controller_fault_count | u16: active controller faults count |
| 227 | controller_flags | u16 bitmask, reserved bits zero |

RO states: 0=unknown, 1=standby, 2=startup_flush, 3=divert, 4=production, 5=shutdown_flush, 6=fault, 7=maintenance. Additional states require a compatible version update. If `fault_count > 1`, only the primary highest-severity fault is in this compact block; future revisions may add a fault-list transport.

**Compatibility:** Existing input registers 100–139 (the polling window is 100–199 as of protocol 1.3; 100–139 is unchanged) and holding registers 200–202 are unchanged. The optional 220–227 extension does not require the sensor node to implement it to remain compatible with the v1 measurement reader. The firmware should expose extension support explicitly and test with older versions.
