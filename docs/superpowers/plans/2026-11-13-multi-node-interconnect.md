# Multi-Node Sensor System and RJ45 Interconnect Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the protocol, host simulator and docs from one sensor node to a bus of identical-hardware nodes (RO skid unit 1, tank unit 2) joined by a standard 24 V RJ45 trunk, with an optional pressure channel on every node.

**Architecture:** Protocol 1.2 keeps one shared 40-word input layout and turns reserved words 133/134 into `node_type` and `installed_mask`, so no v1.1 address moves. The simulator gains per-node profiles and a `Bus` that routes by unit id. A pure `monitor` module models the controller's per-node health and production-permit logic. Hardware docs and a machine-checked pinout define the interconnect.

**Tech Stack:** Python >= 3.11, uv, PyYAML, pymodbus 3.16.x (client), Loguru, pytest, hypothesis, ruff.

**Spec:** `docs/superpowers/specs/2026-11-13-sensor-node-interconnect-design.md`

## Global Constraints

- Use `uv` only (`uv sync`, `uv run pytest`, `uv run python`). Never `pip`, never `python -m venv`.
- Run every command from `host_tools/` unless a step says otherwise. Do not chain shell commands with `&&`; issue separate commands.
- Do not change any existing register address, type, scale, signedness, or access in `protocol/register_map.yaml`. Only registers 133 and 134 (currently reserved) change. Protocol version becomes `1.2`.
- No hardware assumptions: no pinouts beyond the spec's RJ45 table, no sensor voltages, flow calibration, pressure limits. Keep TBDs visible. All simulated values are labelled simulated.
- Never substitute, clamp, wrap, or default a value silently. Raise.
- A sensor-node register must never command an actuator. Nothing here adds a write path.
- Type annotations on every function; Sphinx-style docstrings (`:param x:`, `:returns:`, `:raises:`); `pathlib` for paths; Loguru only in `cli.py` and `sim/server.py`.
- pymodbus is imported only by `client.py` and tests. `sim/` must not import pymodbus.
- Every commit message ends with the trailer line `Assisted-by: Claude Sonnet 5.5 (Claude Code)` and no `Co-Authored-By` line.
- Work on branch `multi-node-interconnect-design`. Do not push. Do not switch branches.
- Full suite (`uv run pytest`) and `uv run ruff check .` must pass at the end of every task.

## File Structure

```
protocol/register_map.yaml                       modify  Task 1
protocol/REGISTER_MAP_REFERENCE.md               modify  Task 1
protocol/examples/sample_snapshot.json           modify  Task 1
docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md      modify  Task 1
docs/superpowers/specs/2026-11-13-...-design.md  modify  Task 1 (section 4 amendment)
host_tools/src/ro_tools/generated/registers.py   regenerate Task 1
host_tools/src/ro_tools/sim/register_bank.py     modify  Task 2
host_tools/src/ro_tools/sim/presets.py           modify  Task 2
host_tools/src/ro_tools/sim/server.py            modify  Task 3 (type annotations only)
host_tools/src/ro_tools/sim/bus.py               create  Task 3
host_tools/src/ro_tools/monitor.py               create  Task 4
host_tools/src/ro_tools/cli.py                   modify  Task 5
hardware/interconnect/pinout.yaml                create  Task 6
hardware/interconnect/NODE_BUS_INTERCONNECT.md   create  Task 6
docs/decisions/ADR-0008-node-bus-interconnect.md create  Task 6
hardware/sensor-node/HARDWARE_SPEC.md            modify  Task 6
hardware/power/POWER_AND_WIRING.md               modify  Task 6
hardware/main-controller/WIRING.md               modify  Task 6
CHANGELOG.md, protocol/README.md                 modify  Task 7
host_tools/tests/test_protocol_v12.py            create  Task 1
host_tools/tests/test_node_identity.py           create  Task 2
host_tools/tests/test_presets_profiles.py        create  Task 2
host_tools/tests/test_bus.py                     create  Task 3
host_tools/tests/test_monitor.py                 create  Task 4
host_tools/tests/test_cli_multinode.py           create  Task 5
host_tools/tests/test_interconnect_docs.py       create  Task 6
host_tools/tests/test_cli.py, test_schema.py     modify  Task 1 (version strings)
```

## Design decisions recorded here (deviation from spec section 4)

The spec text says "one register map per node type". Implementing that means reworking the schema, codegen and every module-level constant. This plan instead uses **one shared layout** with two new identity words:

- Register 133 `node_type` (u16, enum `node_type`: 0 `ro_skid`, 1 `tank`).
- Register 134 `installed_mask` (u16, same bit assignments as `validity_bits`; a set bit means that sensor is physically fitted on this node).
- Invariant: `validity_mask & ~installed_mask == 0`. A sensor that is fitted but failing has its installed bit set and its validity bit clear. A sensor that is not fitted has neither. The existing name `ro_feed_pressure_psi_x10` (address 115, validity bit 6) is the node's optional pressure channel on every node type.
- The controller's per-node requirement comes from its own configuration (`NodeConfig.required_mask`), never from the node's self-report. A node whose `installed_mask` lacks a required bit is `WRONG_NODE`.

Task 1 amends spec section 4 to say this.

---

### Task 1: Protocol 1.2 identity registers

**Files:**
- Modify: `protocol/register_map.yaml` (version minor, registers 133/134, `enums`)
- Modify: `host_tools/tests/test_cli.py:28`, `host_tools/tests/test_schema.py:23,41`
- Create: `host_tools/tests/test_protocol_v12.py`
- Regenerate: `host_tools/src/ro_tools/generated/registers.py`
- Modify: `protocol/REGISTER_MAP_REFERENCE.md`, `protocol/examples/sample_snapshot.json`, `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`, `docs/superpowers/specs/2026-11-13-sensor-node-interconnect-design.md`

**Interfaces:**
- Produces: `reg.PROTOCOL_MINOR == 2`, `reg.ADDR_NODE_TYPE == 133`, `reg.ADDR_INSTALLED_MASK == 134`, `reg.NodeType` (`IntEnum`: `RO_SKID = 0`, `TANK = 1`), `Snapshot.node_type: int`, `Snapshot.installed_mask: int`.

- [ ] **Step 1: Write the failing test**

Create `host_tools/tests/test_protocol_v12.py`:

```python
"""Protocol 1.2 guards: v1.1 addresses are frozen; node identity registers added."""

from ro_tools import schema
from ro_tools.generated import registers as reg

# Frozen v1.1 contract: name -> (address, type, scale_divisor). Never edit these rows.
V11_INPUT: dict[str, tuple[int, str, int]] = {
    "protocol_major": (100, "u16", 1),
    "protocol_minor": (101, "u16", 1),
    "snapshot_sequence": (102, "u16", 1),
    "module_status": (103, "u16", 1),
    "validity_mask": (104, "u16", 1),
    "fault_mask": (105, "u16", 1),
    "critical_age_ms": (106, "u16", 1),
    "uptime_seconds": (107, "u32", 1),
    "feed_ec_us_cm_x10": (109, "u16", 10),
    "permeate_ec_us_cm_x100": (110, "u16", 100),
    "permeate_flow_gpm_x1000": (111, "u16", 1000),
    "concentrate_flow_gpm_x1000": (112, "u16", 1000),
    "permeate_temp_c_x100": (113, "i16", 100),
    "concentrate_temp_c_x100": (114, "i16", 100),
    "ro_feed_pressure_psi_x10": (115, "u16", 10),
    "tank_volume_gal_x100": (116, "u16", 100),
    "load_left_raw": (117, "i32", 1),
    "load_right_raw": (119, "i32", 1),
    "permeate_total_pulses": (121, "u32", 1),
    "concentrate_total_pulses": (123, "u32", 1),
    "boot_counter": (125, "u32", 1),
    "sample_interval_ms": (127, "u16", 1),
    "sensor_error_code": (128, "u16", 1),
    "feed_ec_raw_adc": (129, "u16", 1),
    "permeate_ec_raw_adc": (130, "u16", 1),
    "pressure_raw_adc": (131, "u16", 1),
    "feed_temp_c_x100": (132, "i16", 100),
}


def test_v11_input_registers_unchanged():
    by_name = {r.name: r for r in schema.load().input_registers}
    for name, (addr, typ, div) in V11_INPUT.items():
        r = by_name[name]
        assert (r.address, r.type, r.scale_divisor, r.access) == (addr, typ, div, "read_only"), name


def test_polling_window_unchanged():
    m = schema.load()
    assert (m.input_start, m.input_count) == (100, 40)


def test_node_identity_registers():
    m = schema.load()
    by_name = {r.name: r for r in m.input_registers}
    node_type = by_name["node_type"]
    assert (node_type.address, node_type.type, node_type.enum) == (133, "u16", "node_type")
    installed = by_name["installed_mask"]
    assert (installed.address, installed.type, installed.access) == (134, "u16", "read_only")
    assert m.enums["node_type"] == {0: "ro_skid", 1: "tank"}
    assert (m.version_major, m.version_minor) == (1, 2)


def test_generated_module_exposes_identity():
    assert reg.PROTOCOL_MINOR == 2
    assert reg.ADDR_NODE_TYPE == 133
    assert reg.ADDR_INSTALLED_MASK == 134
    assert int(reg.NodeType.RO_SKID) == 0
    assert int(reg.NodeType.TANK) == 1
    snap = reg.decode_snapshot([0] * reg.INPUT_COUNT)
    assert snap.node_type == 0
    assert snap.installed_mask == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_protocol_v12.py -v`
Expected: `test_v11_input_registers_unchanged` PASSES (guard); the other three FAIL (`KeyError: 'node_type'`, version `(1, 1)`).

- [ ] **Step 3: Edit the YAML**

In `protocol/register_map.yaml`:
1. Change `version: minor: 1` to `minor: 2`.
2. Replace the `reserved_133` and `reserved_134` entries (keep `reserved_135`..`reserved_139` untouched) with:

```yaml
- address: 133
  name: node_type
  type: u16
  words: 1
  scale_divisor: 1
  unit: enum
  access: read_only
  enum: node_type
- address: 134
  name: installed_mask
  type: u16
  words: 1
  scale_divisor: 1
  unit: bitmask
  access: read_only
```
3. Add under `enums:` (before `ro_state:`):

```yaml
  node_type:
    0: ro_skid
    1: tank
```

- [ ] **Step 4: Update version strings in existing tests**

- `host_tools/tests/test_cli.py:28`: `"OK: protocol 1.1, 40 input words"` -> `"OK: protocol 1.2, 40 input words"`.
- `host_tools/tests/test_schema.py:23`: `== (1, 1)` -> `== (1, 2)`.
- `host_tools/tests/test_schema.py:41`: `by_name["reserved_133"]` -> `by_name["reserved_135"]`.

- [ ] **Step 5: Regenerate the codec**

Run: `uv run ro-tools generate`
Then: `uv run ro-tools generate --check` (expect exit 0).
If `reg.NodeType` is missing from the generated module, `codegen.render` (`host_tools/src/ro_tools/codegen.py:205`) only emits enums used by status registers; extend it to emit every entry of `m.enums` as an `IntEnum` (same format as the existing `RoState` at `registers.py:157`), regenerate, and keep `test_codegen.py` passing.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: all pass, including the four new tests. Fix any other test that hard-codes version 1.1 by changing only the expected version.
Run: `uv run ruff check .` (expect no findings).

- [ ] **Step 7: Update docs**

- `protocol/REGISTER_MAP_REFERENCE.md`: add a bullet after the "Reserved fields" line: `- Node identity (protocol 1.2): register 133 node_type (0 ro_skid, 1 tank) and 134 installed_mask (same bit positions as validity_mask; set = sensor physically fitted). validity_mask must be a subset of installed_mask. Fitted-but-failing = installed bit set, validity bit clear. Registers 135-139 remain reserved.`
- `protocol/examples/sample_snapshot.json`: set `"protocol_version": "1.2"` and add `"node_type": "ro_skid"` and `"installed_mask": "0x007F"` (the simulated RO-skid profile).
- `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`: append section `## Node identity and multi-node bus (protocol 1.2)` stating the two registers, the subset invariant, that unit ids 1-15 are set by a 4-position DIP switch on the carrier board, and that a duplicate or out-of-range id leaves the node silent.
- `docs/superpowers/specs/2026-11-13-sensor-node-interconnect-design.md` section 4: replace the first two bullets with the shared-layout description from "Design decisions recorded here" above (shared 40-word layout, `node_type`, `installed_mask`, optional pressure channel semantics).

- [ ] **Step 8: Commit**

```bash
git add protocol docs host_tools
git commit -m "feat(protocol): v1.2 node_type and installed_mask identity registers

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 2: Node identity in the register bank and per-node presets

**Files:**
- Modify: `host_tools/src/ro_tools/sim/register_bank.py`
- Modify: `host_tools/src/ro_tools/sim/presets.py`
- Create: `host_tools/tests/test_node_identity.py`, `host_tools/tests/test_presets_profiles.py`

**Interfaces:**
- Consumes: `reg.NodeType`, `reg.ValidityBits`, `reg.FaultBits`, `Snapshot.node_type`, `Snapshot.installed_mask`.
- Produces:
  - `register_bank.ALL_SENSORS: int` (OR of every `ValidityBits` member).
  - `RegisterBank(clock=..., metadata=..., node_type: int = NodeType.RO_SKID, installed_mask: int = ALL_SENSORS)`.
  - `RegisterBank.configure_node(node_type: int, installed_mask: int) -> None` (raises `ValueError`).
  - `RegisterBank.commit()` raises `ValueError("validity bits 0x.... set for sensors that are not installed")` and publishes nothing if `validity_mask & ~installed_mask`.
  - `presets.NodeProfile` frozen dataclass: `name: str, node_type: int, installed: int, validity: int, fields: dict[str, int], victim: ValidityBits, victim_fault: FaultBits`.
  - `presets.FULL_PROFILE`, `RO_SKID_PROFILE`, `TANK_PROFILE`.
  - `presets.apply_preset(responder, name, profile: NodeProfile = FULL_PROFILE) -> None`; new preset name `"pressure_failed"` appended to `PRESETS`.

- [ ] **Step 1: Write the failing bank tests**

Create `host_tools/tests/test_node_identity.py`:

```python
"""Node identity and the validity-subset-of-installed invariant."""

import struct

import pytest

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank

TANK_MASK = int(V.TANK_VOLUME | V.LEFT_LOAD_CELL | V.RIGHT_LOAD_CELL)


def tank_bank(extra: int = 0) -> RegisterBank:
    return RegisterBank(node_type=reg.NodeType.TANK, installed_mask=TANK_MASK | extra)


def test_default_is_full_ro_skid():
    snap = RegisterBank().published()
    assert snap.node_type == reg.NodeType.RO_SKID
    assert snap.installed_mask == ALL_SENSORS


def test_tank_identity_is_published_after_commit():
    bank = tank_bank()
    bank.commit()
    snap = bank.published()
    assert snap.node_type == int(reg.NodeType.TANK)
    assert snap.installed_mask == TANK_MASK


def test_validity_for_uninstalled_sensor_is_rejected_at_commit():
    bank = tank_bank()
    bank.set_validity(int(V.FEED_EC))
    with pytest.raises(ValueError, match="not installed"):
        bank.commit()


def test_failed_commit_leaves_previous_snapshot_published():
    bank = tank_bank()
    bank.set_validity(TANK_MASK)
    bank.commit()
    before = bank.published()
    bank.set_validity(TANK_MASK | int(V.FEED_EC))
    with pytest.raises(ValueError):
        bank.commit()
    assert bank.published() == before


def test_installed_but_failed_differs_from_not_installed():
    bank = tank_bank(extra=int(V.RO_FEED_PRESSURE))
    bank.set_validity(TANK_MASK)
    bank.commit()
    snap = bank.published()
    assert snap.installed_mask & int(V.RO_FEED_PRESSURE)
    assert not snap.validity_mask & int(V.RO_FEED_PRESSURE)


@pytest.mark.parametrize("node_type", [2, 99, -1, 65536])
def test_bad_node_type_rejected(node_type):
    with pytest.raises(ValueError):
        RegisterBank(node_type=node_type)


@pytest.mark.parametrize("mask", [0x8000, -1, 65536])
def test_bad_installed_mask_rejected(mask):
    with pytest.raises(ValueError):
        RegisterBank(installed_mask=mask)


def test_identity_readable_over_fc04():
    bank = tank_bank()
    bank.commit()
    resp = bank.handle_pdu(struct.pack(">BHH", 4, reg.ADDR_NODE_TYPE, 2))
    assert resp == bytes([4, 4]) + struct.pack(">HH", int(reg.NodeType.TANK), TANK_MASK)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_node_identity.py -v`
Expected: FAIL (`ImportError: cannot import name 'ALL_SENSORS'`).

- [ ] **Step 3: Implement in `register_bank.py`**

Add to the imports from `ro_tools.generated.registers`: `NodeType`, `ValidityBits`. After `_U32_MAX`:

```python
ALL_SENSORS: int = sum(int(bit) for bit in ValidityBits)


def _check_identity(node_type: int, installed_mask: int) -> None:
    """Reject an impossible node identity.

    :param node_type: Candidate ``node_type`` register value.
    :param installed_mask: Candidate ``installed_mask`` register value.
    :raises ValueError: If ``node_type`` is not a defined :class:`NodeType` value or
        ``installed_mask`` has a bit that is not a defined validity bit.
    """
    if node_type not in {int(member) for member in NodeType}:
        raise ValueError(f"node_type {node_type} is not a defined NodeType")
    if installed_mask < 0 or installed_mask & ~ALL_SENSORS:
        raise ValueError(f"installed_mask {installed_mask:#06x} has undefined sensor bits")
```

Change `RegisterBank.__init__` signature to add `node_type: int = int(NodeType.RO_SKID), installed_mask: int = ALL_SENSORS` after `metadata`, document both params, and after `self._pending["sample_interval_ms"] = 1000` add:

```python
        _check_identity(node_type, installed_mask)
        self._pending["node_type"] = node_type
        self._pending["installed_mask"] = installed_mask
```
(these two lines must come before `self._published = Snapshot(**self._pending)`).

Add method:

```python
    def configure_node(self, node_type: int, installed_mask: int) -> None:
        """Change the pending node identity.

        :param node_type: A :class:`NodeType` value.
        :param installed_mask: Bits of the validity mask that are physically fitted.
        :raises ValueError: If either value is impossible (see :func:`_check_identity`).
        """
        _check_identity(node_type, installed_mask)
        with self._lock:
            self._pending["node_type"] = node_type
            self._pending["installed_mask"] = installed_mask
```

At the top of the `with self._lock:` block in `commit()`, before the sequence increment:

```python
            unfitted = self._pending["validity_mask"] & ~self._pending["installed_mask"]
            if unfitted:
                raise ValueError(
                    f"validity bits {unfitted:#06x} set for sensors that are not installed"
                )
```

- [ ] **Step 4: Run bank tests and the full suite**

Run: `uv run pytest tests/test_node_identity.py -v` (expect PASS), then `uv run pytest` (expect all pass; default bank installs every sensor, so existing tests are unaffected).

- [ ] **Step 5: Write the failing preset tests**

Create `host_tools/tests/test_presets_profiles.py`:

```python
"""Per-node simulator profiles and the pressure_failed preset."""

import pytest

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import FaultBits as F
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.sim.presets import (
    FULL_PROFILE,
    PRESETS,
    RO_SKID_PROFILE,
    TANK_PROFILE,
    apply_preset,
)
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank
from ro_tools.sim.server import Responder

RO_MASK = 0x007F
TANK_MASK = int(V.TANK_VOLUME | V.LEFT_LOAD_CELL | V.RIGHT_LOAD_CELL)


def node(profile, preset="healthy", unit_id=1):
    responder = Responder(RegisterBank(), unit_id=unit_id)
    apply_preset(responder, preset, profile)
    return responder


def test_default_profile_is_unchanged_full_node():
    snap = node(FULL_PROFILE).bank.published()
    assert snap.node_type == int(reg.NodeType.RO_SKID)
    assert snap.installed_mask == ALL_SENSORS
    assert snap.validity_mask == 0x03FF


def test_apply_preset_without_profile_matches_full_profile():
    responder = Responder(RegisterBank())
    apply_preset(responder, "healthy")
    assert responder.bank.published() == node(FULL_PROFILE).bank.published()


def test_ro_skid_healthy():
    snap = node(RO_SKID_PROFILE).bank.published()
    assert snap.node_type == int(reg.NodeType.RO_SKID)
    assert snap.installed_mask == RO_MASK
    assert snap.validity_mask == RO_MASK
    assert snap.tank_volume_gal_x100 == 0


def test_tank_healthy():
    snap = node(TANK_PROFILE, unit_id=2).bank.published()
    assert snap.node_type == int(reg.NodeType.TANK)
    assert snap.installed_mask == TANK_MASK
    assert snap.validity_mask == TANK_MASK
    assert snap.feed_ec_us_cm_x10 == 0


def test_critical_sensor_invalid_uses_the_profile_victim():
    tank = node(TANK_PROFILE, "critical_sensor_invalid", 2).bank.published()
    assert not tank.validity_mask & int(V.TANK_VOLUME)
    assert tank.fault_mask & int(F.HX711_LEFT_FAULT)
    ro = node(RO_SKID_PROFILE, "critical_sensor_invalid").bank.published()
    assert not ro.validity_mask & int(V.PERMEATE_EC)
    assert ro.fault_mask & int(F.EC_PERMEATE_FAULT)


def test_pressure_failed_is_installed_but_invalid():
    snap = node(RO_SKID_PROFILE, "pressure_failed").bank.published()
    assert snap.installed_mask & int(V.RO_FEED_PRESSURE)
    assert not snap.validity_mask & int(V.RO_FEED_PRESSURE)
    assert snap.fault_mask & int(F.PRESSURE_FAULT)


def test_pressure_failed_on_node_without_pressure_raises_and_leaves_bank_untouched():
    responder = Responder(RegisterBank(), unit_id=2)
    before = responder.bank.published()
    with pytest.raises(ValueError, match="no pressure channel"):
        apply_preset(responder, "pressure_failed", TANK_PROFILE)
    assert responder.bank.published() == before


def test_pressure_failed_is_a_listed_preset():
    assert "pressure_failed" in PRESETS
```

- [ ] **Step 6: Run to verify it fails**

Run: `uv run pytest tests/test_presets_profiles.py -v`
Expected: FAIL (`ImportError: cannot import name 'FULL_PROFILE'`).

- [ ] **Step 7: Implement in `presets.py`**

Replace the contents of `host_tools/src/ro_tools/sim/presets.py` with the following. Keep `_HEALTHY_FIELDS` and `_HEALTHY_VALIDITY` exactly as they are in the current file (copy them unchanged) because existing tests may import them; only the code after them changes.

```python
"""Named scenario presets. All values are SIMULATED, not equipment limits."""

from __future__ import annotations

from dataclasses import dataclass

from ro_tools.generated.registers import FaultBits, NodeType, StatusBits, ValidityBits
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank
from ro_tools.sim.server import Responder

PRESETS: tuple[str, ...] = (
    "healthy",
    "critical_sensor_invalid",
    "stale",
    "frozen_sequence",
    "silent",
    "pressure_failed",
)

# SIMULATED illustrative values from protocol/examples/sample_snapshot.json.
_HEALTHY_FIELDS: dict[str, int] = {
    "feed_ec_us_cm_x10": 4257,
    "permeate_ec_us_cm_x100": 1830,
    "permeate_flow_gpm_x1000": 350,
    "concentrate_flow_gpm_x1000": 1050,
    "ro_feed_pressure_psi_x10": 1250,
    "tank_volume_gal_x100": 2870,
    "permeate_temp_c_x100": 1500,
    "concentrate_temp_c_x100": 1500,
    "critical_age_ms": 100,
}


_HEALTHY_VALIDITY: int = sum(
    int(bit) for bit in ValidityBits if bit != ValidityBits.FEED_TEMP_OPTIONAL
)

_V = ValidityBits
_RO_BITS: int = int(
    _V.FEED_EC
    | _V.PERMEATE_EC
    | _V.PERMEATE_FLOW
    | _V.CONCENTRATE_FLOW
    | _V.PERMEATE_TEMP
    | _V.CONCENTRATE_TEMP
    | _V.RO_FEED_PRESSURE
)
_TANK_BITS: int = int(_V.TANK_VOLUME | _V.LEFT_LOAD_CELL | _V.RIGHT_LOAD_CELL)


@dataclass(frozen=True)
class NodeProfile:
    """What one simulated node physically has and what a healthy reading looks like.

    :ivar name: Profile name, for messages.
    :ivar node_type: ``node_type`` register value.
    :ivar installed: ``installed_mask`` register value.
    :ivar validity: Validity bits set in the healthy state (subset of ``installed``).
    :ivar fields: SIMULATED healthy raw register values.
    :ivar victim: Validity bit cleared by ``critical_sensor_invalid``.
    :ivar victim_fault: Fault bit raised together with it.
    """

    name: str
    node_type: int
    installed: int
    validity: int
    fields: dict[str, int]
    victim: ValidityBits
    victim_fault: FaultBits


FULL_PROFILE = NodeProfile(
    name="full",
    node_type=int(NodeType.RO_SKID),
    installed=ALL_SENSORS,
    validity=_HEALTHY_VALIDITY,
    fields=_HEALTHY_FIELDS,
    victim=ValidityBits.PERMEATE_EC,
    victim_fault=FaultBits.EC_PERMEATE_FAULT,
)

RO_SKID_PROFILE = NodeProfile(
    name="ro_skid",
    node_type=int(NodeType.RO_SKID),
    installed=_RO_BITS,
    validity=_RO_BITS,
    fields={
        "feed_ec_us_cm_x10": 4257,
        "permeate_ec_us_cm_x100": 1830,
        "permeate_flow_gpm_x1000": 350,
        "concentrate_flow_gpm_x1000": 1050,
        "ro_feed_pressure_psi_x10": 1250,
        "permeate_temp_c_x100": 1500,
        "concentrate_temp_c_x100": 1500,
        "critical_age_ms": 100,
    },
    victim=ValidityBits.PERMEATE_EC,
    victim_fault=FaultBits.EC_PERMEATE_FAULT,
)

TANK_PROFILE = NodeProfile(
    name="tank",
    node_type=int(NodeType.TANK),
    installed=_TANK_BITS,
    validity=_TANK_BITS,
    fields={
        "tank_volume_gal_x100": 2870,
        "load_left_raw": 123456,
        "load_right_raw": 123400,
        "critical_age_ms": 100,
    },
    victim=ValidityBits.TANK_VOLUME,
    victim_fault=FaultBits.HX711_LEFT_FAULT,
)


def _healthy(bank: RegisterBank, profile: NodeProfile) -> None:
    """Load the SIMULATED healthy snapshot for ``profile`` into the pending buffer.

    :param bank: Bank to load.
    :param profile: Node profile.
    """
    bank.configure_node(profile.node_type, profile.installed)
    for name, raw in profile.fields.items():
        bank.set_field(name, raw)
    bank.set_status(StatusBits.OPERATIONAL)
    bank.set_validity(profile.validity)
    bank.set_faults(0)


def apply_preset(
    responder: Responder, name: str, profile: NodeProfile = FULL_PROFILE
) -> None:
    """Apply a named scenario to a responder and commit its bank.

    :param responder: Responder whose bank and drop flag are set.
    :param name: One of :data:`PRESETS`.
    :param profile: Which node is being simulated; defaults to the legacy full node.
    :raises ValueError: If ``name`` is unknown, or ``pressure_failed`` is requested for a
        profile with no pressure channel (the bank is left untouched).
    """
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {PRESETS}")
    if name == "pressure_failed" and not profile.installed & int(ValidityBits.RO_FEED_PRESSURE):
        raise ValueError(f"profile {profile.name!r} has no pressure channel")
    bank = responder.bank
    responder.drop_responses = False
    bank.freeze_sequence(False)
    _healthy(bank, profile)
    if name == "critical_sensor_invalid":
        bank.set_validity(profile.validity & ~int(profile.victim))
        bank.set_faults(profile.victim_fault)
    elif name == "stale":
        bank.force_critical_age(65535)
        bank.set_faults(FaultBits.STALE_ACQUISITION)
    elif name == "frozen_sequence":
        bank.commit()
        bank.freeze_sequence(True)
    elif name == "silent":
        responder.drop_responses = True
    elif name == "pressure_failed":
        bank.set_validity(profile.validity & ~int(ValidityBits.RO_FEED_PRESSURE))
        bank.set_faults(FaultBits.PRESSURE_FAULT)
    bank.commit()
```

- [ ] **Step 8: Run the full suite and lint**

Run: `uv run pytest` (expect all pass), `uv run ruff check .`, `uv run ruff format --check .`. If format check fails, run `uv run ruff format src tests`.

- [ ] **Step 9: Commit**

```bash
git add host_tools
git commit -m "feat(sim): node identity, installed-mask invariant, per-node profiles

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 3: Multi-node simulated bus

**Files:**
- Create: `host_tools/src/ro_tools/sim/bus.py`
- Modify: `host_tools/src/ro_tools/sim/server.py` (annotations only)
- Create: `host_tools/tests/test_bus.py`

**Interfaces:**
- Consumes: `Responder(bank, unit_id)`, `apply_preset(responder, name, profile)`, `TcpSimServer(responder_like)`.
- Produces:
  - `server.SupportsRespond` (`typing.Protocol`: `respond(self, unit: int, pdu: bytes) -> bytes | None`).
  - `bus.Bus`: `add(responder: Responder) -> None` (raises `ValueError` on duplicate id or id outside 1..15), `node(unit_id: int) -> Responder` (raises `KeyError`), `unit_ids -> tuple[int, ...]`, `respond(unit: int, pdu: bytes) -> bytes | None`.

- [ ] **Step 1: Write the failing test**

Create `host_tools/tests/test_bus.py`:

```python
"""Two simulated nodes sharing one bus, polled through the real client."""

import pytest

from ro_tools.client import CommsError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


@pytest.fixture()
def bus_and_server():
    bus = Bus()
    ro = Responder(RegisterBank(), unit_id=1)
    tank = Responder(RegisterBank(), unit_id=2)
    bus.add(ro)
    bus.add(tank)
    apply_preset(ro, "healthy", RO_SKID_PROFILE)
    apply_preset(tank, "healthy", TANK_PROFILE)
    with TcpSimServer(bus) as server:
        yield bus, server


def read(server, unit_id):
    with SensorNodeClient.tcp(*server.address, timeout=0.3, unit_id=unit_id) as client:
        return client.read_snapshot()


def test_each_unit_answers_with_its_own_identity(bus_and_server):
    _, server = bus_and_server
    assert read(server, 1).node_type == int(reg.NodeType.RO_SKID)
    assert read(server, 2).node_type == int(reg.NodeType.TANK)


def test_unknown_unit_gets_no_answer(bus_and_server):
    _, server = bus_and_server
    with pytest.raises(CommsError):
        read(server, 3)


def test_silent_node_does_not_affect_the_other(bus_and_server):
    bus, server = bus_and_server
    bus.node(2).drop_responses = True
    assert read(server, 1).node_type == int(reg.NodeType.RO_SKID)
    with pytest.raises(CommsError):
        read(server, 2)


def test_nodes_keep_independent_sequences(bus_and_server):
    bus, server = bus_and_server
    bus.node(1).bank.commit()
    assert read(server, 1).snapshot_sequence == 2
    assert read(server, 2).snapshot_sequence == 1


def test_duplicate_unit_id_rejected():
    bus = Bus()
    bus.add(Responder(RegisterBank(), unit_id=1))
    with pytest.raises(ValueError, match="already on the bus"):
        bus.add(Responder(RegisterBank(), unit_id=1))


@pytest.mark.parametrize("unit_id", [0, 16, 247])
def test_out_of_range_unit_id_rejected(unit_id):
    with pytest.raises(ValueError, match="outside 1..15"):
        Bus().add(Responder(RegisterBank(), unit_id=unit_id))


def test_unit_ids_sorted():
    bus = Bus()
    bus.add(Responder(RegisterBank(), unit_id=5))
    bus.add(Responder(RegisterBank(), unit_id=2))
    assert bus.unit_ids == (2, 5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_bus.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ro_tools.sim.bus'`).

- [ ] **Step 3: Implement**

In `host_tools/src/ro_tools/sim/server.py`, add after the `Responder` class:

```python
class SupportsRespond(Protocol):
    """Anything a transport can ask to answer one request (a node or a whole bus)."""

    def respond(self, unit: int, pdu: bytes) -> bytes | None:
        """Answer one request, or return None when nothing must be sent."""
        ...
```
and change the type annotations `responder: Responder` to `responder: SupportsRespond` in `_Server.__init__`, `TcpSimServer.__init__`, and `serve_rtu_on` (update their docstrings: "Responder that answers requests" stays accurate). `_Handler.handle` keeps working unchanged. Do not change `Responder` itself.

Create `host_tools/src/ro_tools/sim/bus.py`:

```python
"""Several simulated nodes sharing one RS485 bus, routed by Modbus unit id."""

from __future__ import annotations

from ro_tools.sim.server import Responder

MIN_UNIT_ID = 1
MAX_UNIT_ID = 15


class Bus:
    """A set of :class:`Responder` objects, one per unit id.

    A request for a unit that is not on the bus gets no answer, exactly like a
    missing node on the wire.
    """

    def __init__(self) -> None:
        """Create an empty bus."""
        self._nodes: dict[int, Responder] = {}

    def add(self, responder: Responder) -> None:
        """Attach a node.

        :param responder: Node to attach; its ``unit_id`` is its bus address.
        :raises ValueError: If the id is outside 1..15 or already on the bus.
        """
        unit_id = responder.unit_id
        if not MIN_UNIT_ID <= unit_id <= MAX_UNIT_ID:
            raise ValueError(f"unit id {unit_id} outside {MIN_UNIT_ID}..{MAX_UNIT_ID}")
        if unit_id in self._nodes:
            raise ValueError(f"unit id {unit_id} already on the bus")
        self._nodes[unit_id] = responder

    def node(self, unit_id: int) -> Responder:
        """Return the node with ``unit_id``.

        :param unit_id: Bus address.
        :returns: The attached responder.
        :raises KeyError: If no such node is attached.
        """
        return self._nodes[unit_id]

    @property
    def unit_ids(self) -> tuple[int, ...]:
        """Attached unit ids in ascending order."""
        return tuple(sorted(self._nodes))

    def respond(self, unit: int, pdu: bytes) -> bytes | None:
        """Route one request to its node.

        :param unit: Unit id from the frame.
        :param pdu: Request PDU.
        :returns: The node's response, or None when no node has this id or the node is silent.
        """
        node = self._nodes.get(unit)
        return None if node is None else node.respond(unit, pdu)
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest` (expect all pass), `uv run ruff check .`, `uv run ruff format --check .`.

- [ ] **Step 5: Commit**

```bash
git add host_tools
git commit -m "feat(sim): multi-node Bus routing by unit id

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 4: Controller-side node health model

**Files:**
- Create: `host_tools/src/ro_tools/monitor.py`
- Create: `host_tools/tests/test_monitor.py`

**Interfaces:**
- Consumes: `Snapshot` fields `protocol_major, node_type, installed_mask, validity_mask, fault_mask, critical_age_ms, snapshot_sequence`; `reg.CRITICAL_VALIDITY`, `reg.CRITICAL_MAX_AGE_MS`, `reg.PROTOCOL_MAJOR`, `reg.FaultBits`.
- Produces:
  - `NodeHealth` (`Enum`): `OK, MISSING, WRONG_NODE, STALE, INVALID`.
  - `NodeConfig(unit_id: int, node_type: int, critical: bool, required_mask: int)` frozen dataclass.
  - `critical_required(installed_mask: int) -> int` (critical validity bits that the given node fits).
  - `evaluate(config, snapshot: Snapshot | None, previous_sequence: int | None = None, max_age_ms: int = CRITICAL_MAX_AGE_MS) -> NodeHealth`.
  - `production_permitted(results: Mapping[int, NodeHealth], configs: Sequence[NodeConfig]) -> bool`.

This is a host-side reference model of the logic Stage C firmware must implement (AGENTS.md rule 4: stale, implausible or inconsistent data is invalid and the controller must inhibit production). It performs no I/O.

- [ ] **Step 1: Write the failing test**

Create `host_tools/tests/test_monitor.py`:

```python
"""Controller-side per-node health evaluation and production permit."""

import dataclasses

from hypothesis import given
from hypothesis import strategies as st

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.monitor import (
    NodeConfig,
    NodeHealth,
    critical_required,
    evaluate,
    production_permitted,
)
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder

RO_CFG = NodeConfig(1, int(reg.NodeType.RO_SKID), True, critical_required(RO_SKID_PROFILE.installed))
TANK_CFG = NodeConfig(2, int(reg.NodeType.TANK), True, critical_required(TANK_PROFILE.installed))


def snap(profile, preset="healthy"):
    responder = Responder(RegisterBank(), unit_id=1)
    apply_preset(responder, preset, profile)
    return responder.bank.published()


def test_critical_required_follows_what_the_node_fits():
    assert critical_required(RO_SKID_PROFILE.installed) == 0x0F
    assert critical_required(TANK_PROFILE.installed) == int(V.TANK_VOLUME)


def test_healthy_nodes_are_ok():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE)) is NodeHealth.OK
    assert evaluate(TANK_CFG, snap(TANK_PROFILE)) is NodeHealth.OK


def test_no_reply_is_missing():
    assert evaluate(RO_CFG, None) is NodeHealth.MISSING


def test_wrong_node_type_is_wrong_node():
    assert evaluate(RO_CFG, snap(TANK_PROFILE)) is NodeHealth.WRONG_NODE


def test_node_missing_a_required_sensor_is_wrong_node():
    cfg = dataclasses.replace(TANK_CFG, node_type=int(reg.NodeType.RO_SKID))
    assert evaluate(cfg, snap(RO_SKID_PROFILE)) is NodeHealth.WRONG_NODE


def test_protocol_major_mismatch_is_wrong_node():
    bad = dataclasses.replace(snap(RO_SKID_PROFILE), protocol_major=reg.PROTOCOL_MAJOR + 1)
    assert evaluate(RO_CFG, bad) is NodeHealth.WRONG_NODE


def test_invalid_critical_sensor_is_invalid():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE, "critical_sensor_invalid")) is NodeHealth.INVALID
    assert evaluate(TANK_CFG, snap(TANK_PROFILE, "critical_sensor_invalid")) is NodeHealth.INVALID


def test_old_snapshot_is_stale():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE, "stale")) is NodeHealth.STALE


def test_age_limit_is_inclusive():
    s = snap(RO_SKID_PROFILE)
    at_limit = dataclasses.replace(s, critical_age_ms=reg.CRITICAL_MAX_AGE_MS)
    over = dataclasses.replace(s, critical_age_ms=reg.CRITICAL_MAX_AGE_MS + 1)
    assert evaluate(RO_CFG, at_limit) is NodeHealth.OK
    assert evaluate(RO_CFG, over) is NodeHealth.STALE


def test_unchanged_sequence_is_stale():
    s = snap(RO_SKID_PROFILE)
    assert evaluate(RO_CFG, s, previous_sequence=s.snapshot_sequence) is NodeHealth.STALE
    assert evaluate(RO_CFG, s, previous_sequence=s.snapshot_sequence - 1) is NodeHealth.OK


def test_optional_pressure_failure_does_not_block_a_node_that_does_not_require_it():
    s = snap(RO_SKID_PROFILE, "pressure_failed")
    assert evaluate(RO_CFG, s) is NodeHealth.OK
    needs_pressure = dataclasses.replace(RO_CFG, required_mask=RO_CFG.required_mask | int(V.RO_FEED_PRESSURE))
    assert evaluate(needs_pressure, s) is NodeHealth.INVALID


def test_production_permitted_only_when_every_critical_node_ok():
    configs = [RO_CFG, TANK_CFG]
    both_ok = {1: NodeHealth.OK, 2: NodeHealth.OK}
    assert production_permitted(both_ok, configs) is True
    assert production_permitted({1: NodeHealth.OK}, configs) is False  # tank never reported
    assert production_permitted({1: NodeHealth.OK, 2: NodeHealth.STALE}, configs) is False


def test_production_denied_with_no_critical_node_configured():
    assert production_permitted({}, []) is False
    non_critical = dataclasses.replace(RO_CFG, critical=False)
    assert production_permitted({1: NodeHealth.OK}, [non_critical]) is False


def test_non_critical_node_failure_does_not_block():
    aux = NodeConfig(3, int(reg.NodeType.TANK), False, 0)
    results = {1: NodeHealth.OK, 2: NodeHealth.OK, 3: NodeHealth.MISSING}
    assert production_permitted(results, [RO_CFG, TANK_CFG, aux]) is True


@given(st.sampled_from([h for h in NodeHealth if h is not NodeHealth.OK]), st.sampled_from([1, 2]))
def test_any_bad_critical_node_denies_production(bad, which):
    results = {1: NodeHealth.OK, 2: NodeHealth.OK}
    results[which] = bad
    assert production_permitted(results, [RO_CFG, TANK_CFG]) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_monitor.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'ro_tools.monitor'`).

- [ ] **Step 3: Implement**

Create `host_tools/src/ro_tools/monitor.py`:

```python
"""Reference model of the main controller's per-node health logic (no I/O).

Stage C firmware must reproduce these rules. Stale, missing, mismatched or invalid
data from any critical node denies RO production (AGENTS.md rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ro_tools.generated.registers import (
    CRITICAL_MAX_AGE_MS,
    CRITICAL_VALIDITY,
    PROTOCOL_MAJOR,
    FaultBits,
    Snapshot,
)


class NodeHealth(Enum):
    """Outcome of evaluating one node's latest poll."""

    OK = "ok"
    MISSING = "missing"
    WRONG_NODE = "wrong_node"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True)
class NodeConfig:
    """What the controller expects of one node, from its own configuration.

    :ivar unit_id: Modbus unit id.
    :ivar node_type: Expected ``node_type`` register value.
    :ivar critical: Whether this node must be healthy for RO production.
    :ivar required_mask: Validity bits the controller needs from this node. Never taken
        from the node's own report.
    """

    unit_id: int
    node_type: int
    critical: bool
    required_mask: int


def critical_required(installed_mask: int) -> int:
    """Return the critical validity bits that a node with ``installed_mask`` fits.

    :param installed_mask: A node's ``installed_mask`` (from its design, not a live read).
    :returns: Bit mask of critical validity bits present on that node.
    """
    return int(CRITICAL_VALIDITY) & installed_mask


def evaluate(
    config: NodeConfig,
    snapshot: Snapshot | None,
    previous_sequence: int | None = None,
    max_age_ms: int = CRITICAL_MAX_AGE_MS,
) -> NodeHealth:
    """Judge one node's latest poll.

    :param config: What the controller expects of this node.
    :param snapshot: The decoded snapshot, or None if the poll got no valid reply.
    :param previous_sequence: ``snapshot_sequence`` of the previous accepted poll, if any.
    :param max_age_ms: Largest acceptable ``critical_age_ms`` (inclusive).
    :returns: The node's health; anything but OK must be treated as unusable.
    """
    if snapshot is None:
        return NodeHealth.MISSING
    if snapshot.protocol_major != PROTOCOL_MAJOR or snapshot.node_type != config.node_type:
        return NodeHealth.WRONG_NODE
    if config.required_mask & ~snapshot.installed_mask:
        return NodeHealth.WRONG_NODE
    if previous_sequence is not None and snapshot.snapshot_sequence == previous_sequence:
        return NodeHealth.STALE
    if snapshot.critical_age_ms > max_age_ms or snapshot.fault_mask & int(
        FaultBits.STALE_ACQUISITION
    ):
        return NodeHealth.STALE
    if config.required_mask & ~snapshot.validity_mask:
        return NodeHealth.INVALID
    return NodeHealth.OK


def production_permitted(results: Mapping[int, NodeHealth], configs: Sequence[NodeConfig]) -> bool:
    """Decide whether node health alone permits RO production.

    :param results: Latest health per unit id; a unit with no entry counts as MISSING.
    :param configs: The configured node list.
    :returns: True only if at least one critical node is configured and every critical
        node is OK. This is necessary, not sufficient: other interlocks still apply.
    """
    critical = [c for c in configs if c.critical]
    if not critical:
        return False
    return all(results.get(c.unit_id, NodeHealth.MISSING) is NodeHealth.OK for c in critical)
```

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest` (expect all pass), `uv run ruff check .`, `uv run ruff format --check .` (run `uv run ruff format src tests` if needed, then re-run pytest).

- [ ] **Step 5: Commit**

```bash
git add host_tools
git commit -m "feat(monitor): per-node health and production-permit reference model

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 5: CLI multi-node support

**Files:**
- Modify: `host_tools/src/ro_tools/cli.py`
- Create: `host_tools/tests/test_cli_multinode.py`

**Interfaces:**
- Consumes: `Bus`, `RO_SKID_PROFILE`, `TANK_PROFILE`, `apply_preset`.
- Produces: `ro-tools read --unit-id N` (default 1, 1..15); `ro-tools sim --nodes ro_skid:1,tank:2` (default: unchanged single full node on unit 1). `read` additionally prints `node_type` and `installed_mask` lines (they are snapshot fields, so `SNAPSHOT_LAYOUT` already includes them).

- [ ] **Step 1: Write the failing test**

Create `host_tools/tests/test_cli_multinode.py`:

```python
"""CLI support for unit ids and a multi-node simulator."""

import pytest

from ro_tools import cli
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


def test_read_unit_id_option():
    args = cli.build_parser().parse_args(["read", "--tcp", "h:1", "--unit-id", "2"])
    assert args.unit_id == 2
    assert cli.build_parser().parse_args(["read", "--tcp", "h:1"]).unit_id == 1


@pytest.mark.parametrize("bad", ["0", "16", "x"])
def test_read_unit_id_out_of_range_exits_2(bad):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["read", "--tcp", "h:1", "--unit-id", bad])
    assert exc.value.code == 2


def test_sim_nodes_option_default_is_none():
    assert cli.build_parser().parse_args(["sim", "--tcp", "h:1"]).nodes is None


def test_parse_nodes_accepts_two_nodes():
    parser = cli.build_parser()
    assert cli._parse_nodes(parser, "ro_skid:1,tank:2") == [("ro_skid", 1), ("tank", 2)]


@pytest.mark.parametrize("text", ["ro_skid", "tank:0", "tank:16", "pump:1", "tank:1,tank:1", ""])
def test_parse_nodes_rejects_bad_specs(text):
    with pytest.raises(SystemExit) as exc:
        cli._parse_nodes(cli.build_parser(), text)
    assert exc.value.code == 2


def test_read_selects_the_requested_node(capsys):
    bus = Bus()
    for unit_id, profile in ((1, RO_SKID_PROFILE), (2, TANK_PROFILE)):
        responder = Responder(RegisterBank(), unit_id=unit_id)
        apply_preset(responder, "healthy", profile)
        bus.add(responder)
    with TcpSimServer(bus) as server:
        host, port = server.address
        assert cli.main(["read", "--tcp", f"{host}:{port}", "--unit-id", "2"]) == 0
    out = capsys.readouterr().out
    assert "node_type                  1" in out
    assert "installed_mask             " in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_multinode.py -v`
Expected: FAIL (`unrecognized arguments: --unit-id`).

- [ ] **Step 3: Implement in `cli.py`**

1. Imports: add `from ro_tools.sim.bus import Bus` and extend the presets import to `from ro_tools.sim.presets import PRESETS, RO_SKID_PROFILE, TANK_PROFILE, NodeProfile, apply_preset`.
2. After `_endpoint`, add:

```python
_NODE_PROFILES: dict[str, NodeProfile] = {"ro_skid": RO_SKID_PROFILE, "tank": TANK_PROFILE}


def _unit_id(text: str) -> int:
    """Parse a Modbus unit id in 1..15 (the DIP-switch range).

    :param text: Command-line text.
    :returns: The unit id.
    :raises argparse.ArgumentTypeError: If not an integer in 1..15.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if not 1 <= value <= 15:
        raise argparse.ArgumentTypeError(f"unit id {value} outside 1..15")
    return value


def _parse_nodes(parser: argparse.ArgumentParser, text: str) -> list[tuple[str, int]]:
    """Parse ``TYPE:ID[,TYPE:ID...]`` for ``sim --nodes``.

    :param parser: Parser for usage errors.
    :param text: The option value, e.g. ``ro_skid:1,tank:2``.
    :returns: ``(node type name, unit id)`` pairs in the order given.
    """
    nodes: list[tuple[str, int]] = []
    seen: set[int] = set()
    for item in text.split(","):
        kind, sep, ident = item.partition(":")
        if not sep or kind not in _NODE_PROFILES:
            parser.error(f"--nodes: {item!r} must be TYPE:ID with TYPE in {sorted(_NODE_PROFILES)}")
        try:
            unit = _unit_id(ident)
        except argparse.ArgumentTypeError as exc:
            parser.error(f"--nodes: {item!r}: {exc}")
        if unit in seen:
            parser.error(f"--nodes: unit id {unit} used twice")
        seen.add(unit)
        nodes.append((kind, unit))
    return nodes
```
3. In `build_parser`: on the `sim` sub-parser add `p.add_argument("--nodes", default=None, metavar="TYPE:ID[,...]", help="simulate several nodes, e.g. ro_skid:1,tank:2 (default: one full node, unit 1)")`; on the `read` sub-parser add `p.add_argument("--unit-id", type=_unit_id, default=reg.UNIT_ID, metavar="N")`.
4. `_open_client`: pass `unit_id=args.unit_id` to both `SensorNodeClient.tcp(...)` and `SensorNodeClient.serial(...)`. `publish-status` has no `--unit-id` in this task, so use `getattr(args, "unit_id", reg.UNIT_ID)`.
5. `_cmd_sim`: when `args.nodes is None`, behave exactly as today. Otherwise build `bus = Bus()` and, for each `(kind, unit)` from `_parse_nodes(parser, args.nodes)`, create `Responder(RegisterBank(), unit_id=unit)`, `apply_preset(responder, args.preset, _NODE_PROFILES[kind])` (a `ValueError` from `pressure_failed` on a tank node must print the message to stderr and return `EXIT_FAIL`), `bus.add(responder)`. Pass `bus` to `TcpSimServer` / `serve_rtu_on`. For the commit loop, give `_commit_loop` a first parameter typed `Sequence[Responder]` and commit every bank each period; update the two existing call sites to pass `[responder]` and update any existing test that calls `_commit_loop` directly (grep first; the current tests only cover it indirectly).

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest` (all pass), `uv run ruff check .`, `uv run ruff format --check .`.

- [ ] **Step 5: Commit**

```bash
git add host_tools
git commit -m "feat(cli): --unit-id for read and --nodes for multi-node sim

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 6: Interconnect hardware docs and machine-checked pinout

**Files:**
- Create: `hardware/interconnect/pinout.yaml`, `hardware/interconnect/NODE_BUS_INTERCONNECT.md`, `docs/decisions/ADR-0008-node-bus-interconnect.md`
- Create: `host_tools/tests/test_interconnect_docs.py`
- Modify: `hardware/sensor-node/HARDWARE_SPEC.md`, `hardware/power/POWER_AND_WIRING.md`, `hardware/main-controller/WIRING.md`

**Interfaces:**
- Produces: `hardware/interconnect/pinout.yaml` is the normative pinout; the markdown table must match it (test enforced).

- [ ] **Step 1: Write the failing test**

Create `host_tools/tests/test_interconnect_docs.py`:

```python
"""The RJ45 trunk pinout YAML is normative; the markdown and sanity rules must agree."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PINOUT = REPO / "hardware" / "interconnect" / "pinout.yaml"
DOC = REPO / "hardware" / "interconnect" / "NODE_BUS_INTERCONNECT.md"

POWER = {"+24V"}
GROUND = {"GND"}
DATA = {"RS485_A", "RS485_B"}


def load() -> dict:
    return yaml.safe_load(PINOUT.read_text(encoding="utf-8"))


def test_every_rj45_pin_is_assigned_exactly_once():
    pins = load()["pins"]
    assert sorted(pins) == list(range(1, 9))


def test_signals_are_from_the_known_set():
    known = POWER | GROUND | DATA | {"RESERVED"}
    assert set(load()["pins"].values()) <= known


def test_rs485_pair_is_the_center_pair():
    pins = load()["pins"]
    assert {pins[4], pins[5]} == DATA


def test_power_and_ground_are_doubled_and_reserved_pins_are_unconnected():
    pins = load()["pins"]
    values = list(pins.values())
    assert values.count("+24V") == 2 and values.count("GND") == 2
    assert values.count("RESERVED") == 2


def test_power_pins_not_adjacent_to_rs485_pins():
    pins = load()["pins"]
    for pin in (4, 5):
        for neighbour in (pin - 1, pin + 1):
            if neighbour in pins and neighbour not in (4, 5):
                assert pins[neighbour] not in POWER, (pin, neighbour)


def test_doc_table_matches_yaml():
    names = {
        "+24V": "+24V",
        "GND": "GND",
        "RS485_A": "RS485 A",
        "RS485_B": "RS485 B",
        "RESERVED": "Reserved",
    }
    expected = {pin: names[signal] for pin, signal in load()["pins"].items()}
    found: dict[int, str] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        pins = [p.strip() for p in cells[0].split(",")]
        if all(p.isdigit() for p in pins):
            for pin in pins:
                found[int(pin)] = cells[1]
    assert found == expected
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_interconnect_docs.py -v`
Expected: FAIL (`FileNotFoundError` for `pinout.yaml`).

- [ ] **Step 3: Write the pinout and doc**

Create `hardware/interconnect/pinout.yaml`:

```yaml
# Normative RJ45 trunk pinout for the RO node bus. T568B wiring, shielded Cat5e/Cat6.
# Test: host_tools/tests/test_interconnect_docs.py
connector: RJ45 shielded, red cable and jacks, label "RO BUS - 24V"
supply_nominal_v: 24
pins:
  1: "+24V"
  2: "+24V"
  3: RESERVED
  4: RS485_A
  5: RS485_B
  6: RESERVED
  7: GND
  8: GND
shell: SHIELD
```

Create `hardware/interconnect/NODE_BUS_INTERCONNECT.md` with sections: Purpose; Cable (shielded Cat5e/Cat6, red); Pinout table; Topology (daisy chain controller -> node 1 -> node 2, each node has IN and OUT jacks wired in parallel, short stubs only); Termination and bias (120 ohm switchable at the two end nodes only; bias at the controller only; resistor values TBD pending transceiver choice); Shield (shell bonded to chassis at the controller end only); Power (one 24 V supply, also feeds the controller; node current under 200 mA is an ASSUMPTION; max trunk length and voltage drop TBD, measure in Stage D); **Ethernet hazard** (distinct color, "RO BUS - 24V" label, never terminate in a switch or patch panel, never plug into the controller's Ethernet port); Node ID (4-position DIP switch, IDs 1-15, duplicate or out-of-range id leaves the node silent); Open TBDs. The pinout table must be exactly this (one row per pin or pair, first column the pin numbers):

```markdown
| Pin | Signal |
|---|---|
| 1, 2 | +24V |
| 3, 6 | Reserved |
| 4 | RS485 A |
| 5 | RS485 B |
| 7, 8 | GND |
| Shell | Shield |
```

Create `docs/decisions/ADR-0008-node-bus-interconnect.md` (status Proposed) recording: multi-node bus of identical carrier boards; RJ45 chosen by the owner over M12 despite the Ethernet-confusion risk, mitigated by color, label and policy; 24 V trunk power; non-isolated RS485 because the trunk carries common GND (isolated footprint kept as an option, to be verified in Stage D); consequences and open TBDs.

Edit existing docs:
- `hardware/sensor-node/HARDWARE_SPEC.md`: replace "12V input, 5V buck..." bullet with the 24 V trunk input (fuse, reverse-polarity, TVS, 5 V buck, 3.3 V regulation, each sensor supply still to be verified); add a "Node types" section (RO skid: ADS1115 x2, 2 PCNT pulse inputs, EC modules, thermistors, optional pressure; tank: HX711 x2, ADS1115 for optional pressure); add "Optional pressure channel (all nodes)": 5 V transducer excitation pin, protection network, solder jumper selecting 0.5-4.5 V ratiometric or 4-20 mA (250 ohm sense resistor, loop power from 24 V), monitoring only, hardwired cutoff still mandatory; add DIP-switch node id; link to `hardware/interconnect/NODE_BUS_INTERCONNECT.md`. Keep every existing TBD.
- `hardware/power/POWER_AND_WIRING.md`: add a bullet "24VDC node bus: one supply feeds the controller and all sensor nodes through the RJ45 trunk (see hardware/interconnect/NODE_BUS_INTERCONNECT.md); fuse per node." Do not remove the 12 VDC bullets; note that the controller accepts 7-36 V and the supply choice for valves and contactor coil remains TBD.
- `hardware/main-controller/WIRING.md`: in section 3 (RS485 to the sensor node) add a note that the RS485 A/B/GND terminals feed an RJ45 trunk jack per the interconnect pinout, that the bus now serves multiple nodes, and keep the existing `[T]` verification warnings. Read the section first and edit in place.

- [ ] **Step 4: Run tests and lint**

Run: `uv run pytest` (all pass), `uv run ruff check .`, `uv run ruff format --check .`.

- [ ] **Step 5: Commit**

```bash
git add hardware docs host_tools
git commit -m "docs(hardware): RJ45 24V node bus interconnect, ADR-0008, optional pressure channel

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

### Task 7: Changelog, protocol README, final verification

**Files:**
- Modify: `CHANGELOG.md`, `protocol/README.md`, `host_tools/README.md`

- [ ] **Step 1: Update docs**

- `CHANGELOG.md`: add section `## Multi-node bus and RJ45 interconnect — 2026-11-13` summarizing: protocol 1.2 (`node_type`, `installed_mask`, no existing address changed), simulator profiles and `Bus`, `monitor` reference model, CLI `--unit-id`/`--nodes`, ADR-0008, interconnect pinout, optional pressure channel on every node.
- `protocol/README.md`: add a sentence that protocol 1.2 adds node identity (registers 133/134) for multi-node buses and that `validity_mask` must be a subset of `installed_mask`.
- `host_tools/README.md`: document `ro-tools sim --nodes ro_skid:1,tank:2` and `ro-tools read --unit-id 2` with one example each.

- [ ] **Step 2: Full verification**

Run each separately:
- `uv run pytest` (expect all pass; report the counts)
- `uv run ruff check .` (expect clean)
- `uv run ruff format --check .` (expect clean)
- `uv run ro-tools validate` (expect `OK: protocol 1.2, 40 input words`)
- `uv run ro-tools generate --check` (expect exit 0)

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md protocol host_tools
git commit -m "docs: changelog and READMEs for multi-node bus

Assisted-by: Claude Sonnet 5.5 (Claude Code)"
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| 1 Scope (two nodes, extensible) | 2, 3, 5 |
| 2 Interconnect (pinout, topology, Ethernet hazard, termination) | 6 |
| 3 Node hardware (carrier board, DIP id, optional pressure) | 6 |
| 4 Protocol (identity, installed mask, pressure semantics, controller node list) | 1, 2, 4 |
| 5 Firmware | Out of scope here: Stage B firmware is not started. Task 1's generated codec and Task 4's reference model are its contract. |
| 6 Testing (N simulated nodes, duplicate id, dropout, stale, uninstalled vs failed) | 2, 3, 4 |
| 7 Open TBDs | 6 (kept visible) |
