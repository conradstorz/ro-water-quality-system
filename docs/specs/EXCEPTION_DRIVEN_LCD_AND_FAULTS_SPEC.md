# Exception-driven local LCD and fault presentation — Draft 0.4

## Intent and scope
The sensor-node ESP32 owns a **read-only 20×4 LCD**. The display presents the most actionable **currently valid** information. Fault severity overrides routine page rotation. Display behavior must never influence measurement acquisition, Modbus timing, or actuator control. The main RO controller alone decides whether to operate pumps/valves; hardwired protections remain independent.

## Severity and display policy
| Rank | Severity | Trigger examples | Display policy |
|---|---|---|---|
| 0 | CRITICAL | Main controller reports latched RO fault; confirmed invalid critical sensor while production is active; pressure/flow unsafe per main controller | Preempt current page immediately; remain on critical fault pages until resolved; cycle equal-severity faults every 5 seconds; show fault count |
| 1 | WARNING | Quality rejection below configured threshold; anomalous pressure/flow trend; sensor degraded but not required in current mode | Preempt normal pages; cycle active warning pages every 5 seconds |
| 2 | ADVISORY | Calibration due; repeated transient communications error; low-priority diagnostics | Show periodically, ahead of normal pages, without obscuring higher severity |
| 3 | NORMAL | No active higher priority conditions | Rotate quality, hydraulics, tank, and diagnostics pages every 5 seconds |

**All thresholds, debounce intervals, and which sensors are critical by RO state are commissioning configuration, not hardcoded guesses.** The node can independently flag sensor invalidity, staleness, ADC errors, and disconnected probes. It must NOT infer main-controller pump state from measured flow. If no current controller status is available, show `CTRL STATUS UNKNOWN` and never claim `PUMP STOPPED` or `SYSTEM SAFE`.

## Source of truth and authority
- Sensor node owns local sensor faults and local acquisition timestamps; main controller owns RO operational state, system faults, latching, shutdown decisions, and persistent system fault history.
- Main controller may write a **display-only status block** over Modbus RTU (see `protocol/register_map.yaml` and `protocol/CONTROLLER_STATUS_EXTENSION.md`). This block is not an actuator command and cannot clear faults or alter sensor calibration.
- Main controller status expires after 3 seconds without a valid complete update; expiry raises a local communications advisory/warning and marks all controller-derived information UNKNOWN. Do not show stale controller states as current.
- When the main controller itself cannot communicate with the node, it must implement its own critical-data timeout and fail-safe shutdown. The LCD is not part of this safety mechanism.

## Fault record model
Every active fault record has: `code`, `source` (`sensor` or `controller`), `severity`, `first_seen_monotonic_ms`, `last_seen_monotonic_ms`, `active`, `acknowledged` (informational only), `measurement_id` (optional), and a bounded `display_message` (20 characters per row). Main controller faults additionally have `fault_code` from the controller status block. No free-form Modbus strings are required in v1: local lookup tables map codes to text.

Use deterministic ordering: severity ascending, then oldest active first, then numeric fault code. Coalesce duplicate reports of the same source+code. Deactivation is driven by verified recovery or explicit main-controller fault-state change, never by LCD page rotation or acknowledgement. Never infer controller fault cleared merely because its status update went stale.

## Display content
- Each row max 20 visible characters, 4 rows total. Critical template: row 1 `!! CRITICAL  1/2 !!`, row 2 short fault description, row 3 affected measurement and current value or `---`, row 4 `RO STATE: <state>` only if controller status is fresh; otherwise `CTRL STATUS UNKNOWN`.
- Warning template: row 1 `! WARNING    1/2 !`, row 2 description, row 3 affected measurement, row 4 recommended action or source.
- Advisory: show summary with frequency configurable; do not permanently hide normal readings for a minor notice.
- Normal pages: quality, flow/recovery, storage, diagnostics. Rejection and recovery calculations are displayed only when all required input values are valid and denominator is nonzero.
- Invalid or stale values must display `---` or `ERR`, not the previous good reading without qualification. Last-good readings may appear only with an explicit `LAST GOOD` label.
- Never display drinking-water safety claims from conductivity alone.

## Scheduling and robustness
- Display refresh target 1 Hz; event-driven critical preemption on next display service iteration (target <= 250 ms if LCD responsive). Page rotation default 5 s, configurable.
- Nonblocking cooperative update; bounded I²C transactions, no display sleeps in acquisition or Modbus handling. LCD absence, I²C lockup, or backlight failure must not prevent reporting.
- On restart show `STARTING / DATA WAIT` until real measurements are valid. If main-controller status never arrives, diagnostics must make that clear.
- Local LCD page cycling does not modify any Modbus register or change controller state.

## Testing / acceptance
1. Simulate multiple faults of different severity: always show highest first, then oldest among equals; confirm fault count.
2. Inject a critical fault during normal page rotation: preempt within 250 ms under healthy LCD conditions.
3. Resolve highest fault: automatically show next highest; never clear latches in main controller.
4. Drop sensor data: mark invalid and display `---` rather than plausible stale values.
5. Stop controller status updates: after 3 s show `CTRL STATUS UNKNOWN`; retain local sensor faults and never assert pump state.
6. Inject unknown controller fault code: display `CTRL FAULT <code>` rather than dropping the fault.
7. Disconnect LCD or force I²C timeouts: sensor acquisition, flow counting, and Modbus continue.
8. Validate all display strings fit 20 columns; no flicker due to full-screen clearing every second.
9. Confirm Modbus write validation rejects incomplete, unauthorized, or out-of-range controller-status writes.

## Implementation interfaces (suggested)
- `firmware/sensor_node/services/fault_manager.py`: merge and prioritize faults, no hardware access.
- `firmware/sensor_node/services/lcd_display.py`: render snapshots and faults; nonblocking scheduler.
- `firmware/sensor_node/protocol/controller_status.py`: validated status block ingestion, freshness.
- `firmware/main_controller/protocol/status_publisher.py`: write state/fault summary; no actuator command semantics.
- `firmware/sensor_node/tests/`: priority, expiry, string-length, and failure-injection tests.
