# ro_tools: host-side protocol tooling

Host-side Python tools for the sensor-node Modbus protocol. They need no hardware: a simulated sensor node stands in for it. `protocol/register_map.yaml` is the single source of truth; this package validates it, generates the Python codec from it, simulates a sensor node (Modbus TCP and serial RTU) with fault injection, and provides a client and the `ro-tools` CLI.

## Setup and tests

Run from `host_tools/`. Use `uv` only.

```
uv sync
uv run pytest
```

## Commands

```
uv run ro-tools validate [PATH]
uv run ro-tools generate [--check]
uv run ro-tools sim (--tcp HOST:PORT | --serial DEVICE) [--preset NAME] [--period SECONDS]
uv run ro-tools read (--tcp HOST:PORT | --serial DEVICE) [--timeout S]
uv run ro-tools publish-status (--tcp HOST:PORT | --serial DEVICE) --state NAME [options]
```

- `validate`: check the register map; prints `OK: protocol 1.1, 40 input words`, or one violation per line on stderr (exit 1).
  `uv run ro-tools validate`
- `generate`: rewrite `generated/registers.py`; `--check` writes nothing and exits 1 on drift.
  `uv run ro-tools generate --check`
- `sim`: run the simulated sensor node until Ctrl-C. A new snapshot is committed every `--period` seconds (default 1.0). Presets: `healthy` (default), `critical_sensor_invalid`, `stale`, `frozen_sequence`, `silent`.
  `uv run ro-tools sim --tcp 127.0.0.1:5020 --preset healthy`
- `read`: print one decoded snapshot, one line per field, with scaled values and units, the validity bits set, and whether all critical validity bits are set. Exit 2 on communication failure, 3 on a Modbus exception.
  `uv run ro-tools read --tcp 127.0.0.1:5020`
- `publish-status`: write one display-only controller status block (exit 2 / 3 as for `read`). Options: `--pump off|on|unknown` (default `unknown`), `--fault-code`, `--severity`, `--fault-count`, `--sequence`. The simulator rejects inconsistent fault code/severity/count with a Modbus exception.
  `uv run ro-tools publish-status --tcp 127.0.0.1:5020 --state production --pump on --sequence 1`

## Generated code

`src/ro_tools/generated/registers.py` is generated and is never hand-edited. After any change to `protocol/register_map.yaml`, regenerate it with `uv run ro-tools generate`.

## Simulated values

All values served by the simulator are simulated. They are not equipment limits and carry no hardware assumptions.

## Not implemented here

Snapshot acceptance, freshness expiry and fault prioritisation are deliberately not implemented. `read` displays register contents only; it makes no accept/reject decision and no claim that the system or water is safe.
