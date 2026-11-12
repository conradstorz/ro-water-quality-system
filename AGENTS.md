# Agent instructions
1. Read `docs/CLAUDE_IMPLEMENTATION_BRIEF.md`, `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`, `protocol/register_map.yaml`, and `docs/safety/SAFETY_REQUIREMENTS.md` before changing firmware.
2. Do not change register addresses, scaling, signedness, or write permissions without a protocol version change and matching tests/docs.
3. Never bypass hardwired protection or energize the mains pump during development. Default outputs off, flush valve unpowered/open, permeate diversion to drain.
4. Treat sensor loss, stale Modbus data, implausible readings, and inconsistent snapshots as invalid. Main controller must inhibit/stop RO production.
5. Do not guess hardware pinouts, sensor voltages, flow calibration, pressure limits, or membrane recovery limits. Record TBDs and provide mock interfaces.
6. Prefer modular code, type annotations, Sphinx-style docstrings, pathlib, pytest/hypothesis for host-side tests, and Loguru for host tools. Use `uv` for Python dependencies.
7. Make incremental changes with tests and concise changelog entries; avoid premature framework complexity.

- The LCD must be exception-driven. Read `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md` and `protocol/CONTROLLER_STATUS_EXTENSION.md` before modifying display or Modbus code.
- The main-controller-to-sensor-node status block is display-only and must never be used as an actuator command.
