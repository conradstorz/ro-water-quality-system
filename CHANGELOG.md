# Changelog
## 0.1 — 2026-11-10
- Initial Git-ready architecture, subsystem spec, Modbus contract, hardware and safety scaffolding.

## Draft 0.3
- Added optional 20x4 I2C sensor-node LCD specification and ADR-0004.

## Draft 0.4 — 2026-11-11
- Specified exception-driven LCD fault priority, deterministic arbitration, controller-status freshness, and fail-safe display behavior.
- Added optional atomic Modbus FC16 display-only controller-status extension (holding registers 220–227); input measurement addresses unchanged.
- Added fault-code catalog, ADR-0005, and LCD fault-injection acceptance matrix.

## Stage A protocol tooling — 2026-11-11
- Added `ro_tools` host package: register-map validator, Python codec generator, simulated Modbus sensor node (TCP and serial RTU) with fault injection, pymodbus-based client, and `ro-tools` CLI.
- Added machine-readable enums, controller-flag bits, and fault codes to `protocol/register_map.yaml` (additive; protocol remains 1.1, no address/scale/signedness/access change).
- FC03 read-back of status registers 220–227 is permitted; status writes with inconsistent fault code/severity/count are rejected.
- Corrected `protocol/examples/sample_snapshot.json` protocol version to 1.1.
