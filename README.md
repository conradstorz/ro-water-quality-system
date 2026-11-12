# RO Water Quality System

Git-ready project scaffold for a well-water reverse-osmosis system supplying two ice makers and a drinking-water faucet.

## Architecture
- **Main controller:** industrial 8-relay ESP32-S3, RO pump/valves/safety supervision, Ethernet/Home Assistant integration.
- **Sensor node:** separate ESP32, analog and digital acquisition, RS485 Modbus RTU **server**, no authority to actuate pumps/valves.
- **Independent protection:** motor-rated contactor, hardwired high-pressure/high-tank-level interlocks, mechanical pressure relief; distribution pump independently controlled by pressure switch and low-water cutoff.

**Start here:** `docs/CLAUDE_IMPLEMENTATION_BRIEF.md`, then `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md` and `protocol/register_map.yaml`.

## Project status
Architecture and interface specification only. Firmware files are placeholders. No pump or valve should be energized by unverified firmware. Exact pump, membrane, sensors, controller pinout, and safety ratings are TBD.

## Development
Python host tooling uses `uv` (no pip). Embedded firmware platform selection is an explicit early decision; do not silently assume MicroPython on the industrial board. Use test doubles and simulated Modbus first.

Local sensor-node LCD: see docs/specs/SENSOR_NODE_LCD_SPEC.md (draft 0.3).

## Draft 0.4 LCD priority behavior
The sensor-node 20×4 LCD now prioritizes critical faults, warnings, and advisories over routine pages. See `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md` and `protocol/CONTROLLER_STATUS_EXTENSION.md`. All sensor and controller values shown on the display must be fresh and valid.
