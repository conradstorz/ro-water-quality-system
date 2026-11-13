# Changelog
## 0.1 — 2026-11-10
- Initial Git-ready architecture, subsystem spec, Modbus contract, hardware and safety scaffolding.

## Draft 0.3
- Added optional 20x4 I2C sensor-node LCD specification and ADR-0004.

## Draft 0.4 — 2026-11-11
- Specified exception-driven LCD fault priority, deterministic arbitration, controller-status freshness, and fail-safe display behavior.
- Added optional atomic Modbus FC16 display-only controller-status extension (holding registers 220–227); input measurement addresses unchanged.
- Added fault-code catalog, ADR-0005, and LCD fault-injection acceptance matrix.

## Permeate diversion decision — 2026-11-12
- Added ADR-0006 (proposed): permeate diversion is a normally closed quality-control dump valve on a tee drain branch, not a fail-to-drain safety function.
- Updated safety requirements, P&ID, acceptance tests, main-controller relay K3 description and AGENTS.md rule 3 to match; added permeate back-pressure requirement (highest line point about 5 ft above membrane).

## Stage A protocol tooling — 2026-11-11
- Added `ro_tools` host package: register-map validator, Python codec generator, simulated Modbus sensor node (TCP and serial RTU) with fault injection, pymodbus-based client, and `ro-tools` CLI.
- Added machine-readable enums, controller-flag bits, and fault codes to `protocol/register_map.yaml` (additive; protocol remains 1.1, no address/scale/signedness/access change).
- FC03 read-back of status registers 220–227 is permitted; status writes with inconsistent fault code/severity/count are rejected.
- Corrected `protocol/examples/sample_snapshot.json` protocol version to 1.1.
- Client verifies every reply against its request (function code, register count, FC16 echo, exception code) and raises `ProtocolError`; exception errors report the request's function code.
- Status-block safeguards: `ControllerStatus` has no defaults, `read_status()` returns `None` for a never-written block, the simulated bank exposes `last_status_sequence_progress_ms` (schema models `require_sequence_progress`), and the boot counter saturates and flags overflow on `reboot()`.
- Simulator logs each rejected request at WARNING with its reason (`bank.last_rejection`) and ignores requests with function code >= 0x80; added `ro-tools -v`.
- Schema hardening: duplicate YAML mapping keys and duplicate `critical_validity_bits` are rejected, Python keywords and unusable generated member names are rejected, wrong-typed values are reported as violations instead of `TypeError`, and generated masks use bitwise OR.
- Serial simulator: suppresses the echo of its own transmission and splits closely spaced RTU frames by request length instead of discarding the merged burst.
