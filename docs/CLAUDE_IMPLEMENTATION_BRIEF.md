# Claude Code implementation brief

## Objective
Implement a robust ESP32 sensor acquisition node that serves versioned measurements over RS485/Modbus RTU to an industrial ESP32-S3 RO controller. Establish simulated integration before using real pumps or valves.

## Read order
1. `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`
2. `protocol/register_map.yaml`
3. `docs/safety/SAFETY_REQUIREMENTS.md`
4. `hardware/sensor-node/HARDWARE_SPEC.md`
5. `docs/test/ACCEPTANCE_TEST_PLAN.md`

## Deliver in stages
**Stage A — protocol tooling:** validate YAML map; generate typed register constants/decoder/encoder and tests; build simulated Modbus server and client. Include address-base, signed and 32-bit word-order tests.

**Stage B — sensor node:** choose documented embedded runtime after checking ESP32 variants; implement drivers behind interfaces, coherent snapshots, health/status, timeout-aware Modbus RTU server, and persistent calibration with version+CRC. No sensor may be silently substituted by a plausible number.

**Stage C — main controller integration:** Modbus RTU client, periodic polling, freshness checks, validity checks, state-machine inputs, and fault events. Pump outputs remain disabled until bench acceptance passes.

**Stage D — hardware:** validate pin assignments, electrical levels, RS485 bias/termination/isolation, sensor excitation, grounding, power budgeting, and noise performance.

**Stage E — commissioning:** test with dummy loads, then hydraulics under supervised conditions after independent safety devices are verified.

## Explicit non-goals for first implementation
- No automatic recovery optimization or proportional concentrate valve.
- No sensor-node command to operate actuators.
- No assumption that Modbus provides safety certification.
- No mandatory Wi-Fi or cloud dependency.

## Completion criteria
- All protocol fields are documented and tested.
- No conflicting GPIO assignments.
- Client detects disconnected, stale, corrupted, and faulted node.
- Node reboots safely and resumes reporting without fabricated values.
- Full offline simulated test harness passes.
- Hardware-dependent TBDs remain visible until resolved.

LCD follow-on task: implement the optional read-only 20x4 I2C display per docs/specs/SENSOR_NODE_LCD_SPEC.md after Stage A protocol tests. Never let LCD I2C block Modbus or acquisition.

## Stage F — exception-driven LCD (required for initial repository)
Read `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md`, `docs/specs/FAULT_CODE_CATALOG.md`, and `protocol/CONTROLLER_STATUS_EXTENSION.md`. Implement a pure fault-priority engine and test it on the host before integrating the LCD. Add the optional atomic FC16 status publisher/receiver and 3-second freshness logic; preserve the original measurement register offsets. Do not implement actuator commands via sensor-node registers. Test unplugged LCD and disconnected RS485 independently.
