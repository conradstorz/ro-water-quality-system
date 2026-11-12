# Stage A Protocol Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate `protocol/register_map.yaml`, generate a typed Python codec from it, and provide a simulated Modbus sensor node plus client, all host-side.

**Architecture:** `schema` loads the YAML into a frozen model; `codegen` renders `generated/registers.py` (committed, drift-tested). A pure `RegisterBank` answers Modbus PDUs; thin TCP and serial-RTU transports wrap it. The client uses pymodbus, so the hand-written server is cross-checked by an independent Modbus implementation.

**Tech Stack:** Python >= 3.11, uv, PyYAML, pymodbus 3.16.x (client only), pyserial, Loguru, pytest, hypothesis, ruff.

**Spec:** `docs/superpowers/specs/2026-11-11-stage-a-protocol-tooling-design.md`

## Global Constraints

- Use `uv` only (`uv sync`, `uv run pytest`, `uv run python`). Never `pip`, never `python -m venv`.
- Run every command from `host_tools/` unless a step says otherwise. Do not chain shell commands with `&&`; issue separate commands.
- Do not change any register address, type, scale, signedness, or access in `protocol/register_map.yaml`. Additions only. Protocol version stays `1.1`.
- No hardware assumptions: no pinouts, voltages, calibration values, or pressure limits. All simulated values are labelled simulated.
- Never substitute, clamp, wrap, or default a value silently. Raise.
- Type annotations on every function; Sphinx-style docstrings (`:param x:`, `:returns:`, `:raises:`); `pathlib` for paths; Loguru only in `cli.py` and `sim/server.py`.
- pymodbus is imported only by `client.py` and tests. `sim/` must not import pymodbus.
- pymodbus 3.16 keyword names: `device_id=` (not `slave=`), `count=` keyword-only.
- Every commit message ends with the trailer line `Assisted-by: <model name> (Claude Code)` and no `Co-Authored-By` line.
- Work on branch `stage-a-protocol-tooling`. Do not push.

## File Structure

```
host_tools/
  pyproject.toml                      modify
  README.md                           modify (Task 6)
  src/ro_tools/__init__.py            create
  src/ro_tools/schema.py              create  Task 1
  src/ro_tools/codegen.py             create  Task 2
  src/ro_tools/generated/__init__.py  create  Task 2
  src/ro_tools/generated/registers.py create  Task 2 (generated)
  src/ro_tools/sim/__init__.py        create  Task 3
  src/ro_tools/sim/register_bank.py   create  Task 3
  src/ro_tools/sim/frames.py          create  Task 4
  src/ro_tools/sim/server.py          create  Task 4
  src/ro_tools/sim/presets.py         create  Task 4
  src/ro_tools/client.py              create  Task 5
  src/ro_tools/cli.py                 create  Task 6
  tests/test_schema.py                create  Task 1
  tests/test_docs_consistency.py      create  Task 1
  tests/test_codegen.py               create  Task 2
  tests/test_codec.py                 create  Task 2
  tests/test_register_bank.py         create  Task 3
  tests/test_frames.py                create  Task 4
  tests/test_server.py                create  Task 4
  tests/test_client_integration.py    create  Task 5
  tests/test_cli.py                   create  Task 6
protocol/register_map.yaml            modify  Task 1 (additive)
protocol/examples/sample_snapshot.json modify Task 1
CHANGELOG.md                          modify  Task 6
```

`host_tools/src/.gitkeep` is deleted in Task 1. `host_tools/tests/test_register_map.py` stays untouched and must keep passing.

---

### Task 1: Packaging, register-map metadata, schema model and validator

**Files:**
- Modify: `host_tools/pyproject.toml`, `protocol/register_map.yaml`, `protocol/examples/sample_snapshot.json`
- Delete: `host_tools/src/.gitkeep`
- Create: `host_tools/src/ro_tools/__init__.py`, `host_tools/src/ro_tools/schema.py`
- Test: `host_tools/tests/test_schema.py`, `host_tools/tests/test_docs_consistency.py`

**Interfaces:**
- Consumes: nothing.
- Produces (`ro_tools.schema`):

```python
DEFAULT_MAP_PATH: Path   # <repo>/protocol/register_map.yaml == Path(__file__).resolve().parents[3] / "protocol" / "register_map.yaml"

class SchemaError(Exception):
    violations: list[str]          # every violation found, not just the first

@dataclass(frozen=True)
class Register:
    address: int
    name: str
    type: str                      # "u16" | "i16" | "u32" | "i32"
    words: int
    scale_divisor: int             # 1 when the YAML omits it
    unit: str | None
    access: str                    # "read_only" | "write_multiple_only"
    enum: str | None               # key into RegisterMap.enums
    equals: int | None
    @property
    def reserved(self) -> bool: ...   # name.startswith("reserved_")

@dataclass(frozen=True)
class FaultCode:
    code: int
    source: str                    # "controller" | "sensor"
    default_severity: str          # a name in enums["fault_severity"]
    description: str
    state_dependent: bool          # False when the YAML omits it

@dataclass(frozen=True)
class RegisterMap:
    version_major: int
    version_minor: int
    unit_id: int
    baud: int
    data_bits: int
    parity: str                    # as in YAML: "even" | "odd" | "none"
    stop_bits: int
    input_start: int
    input_count: int
    period_ms: int
    critical_max_age_ms: int
    client_loss_timeout_ms: int
    validity_bits: dict[int, str]
    critical_validity_bits: tuple[int, ...]
    status_bits: dict[int, str]
    fault_bits: dict[int, str]
    controller_flags_bits: dict[int, str]
    input_registers: tuple[Register, ...]     # sorted by address
    holding_registers: tuple[Register, ...]   # sorted by address
    status_start: int
    status_count: int
    status_timeout_ms: int
    status_schema_major: int
    enums: dict[str, dict[int, str]]
    fault_codes: tuple[FaultCode, ...]        # sorted by code

def parse(raw: dict) -> RegisterMap: ...      # raises SchemaError
def load(path: Path = DEFAULT_MAP_PATH) -> RegisterMap: ...   # yaml.safe_load then parse
```

- [ ] **Step 1: Packaging**

Replace `host_tools/pyproject.toml` with:

```toml
[project]
name = "ro-water-quality-tools"
version = "0.1.0"
description = "Host-side protocol tooling for RO controller"
requires-python = ">=3.11"
dependencies = [
    "pyyaml>=6.0",
    "pymodbus[serial]~=3.16.0",
    "pyserial>=3.5",
    "loguru>=0.7",
]

[project.scripts]
ro-tools = "ro_tools.cli:main"

[dependency-groups]
dev = ["pytest>=8", "hypothesis>=6", "ruff>=0.8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/ro_tools"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
extend-exclude = ["src/ro_tools/generated"]
```

Delete `host_tools/src/.gitkeep`. Create `host_tools/src/ro_tools/__init__.py` containing one line: `"""Host-side protocol tooling for the RO water quality system."""`. Confirm the repo `.gitignore` ignores `.venv/` and `__pycache__/`; add those two lines if missing. Run `uv sync`; expected: resolves and creates `uv.lock` (commit it).

- [ ] **Step 2: Register-map additions**

Append to `protocol/register_map.yaml` (top-level keys, after `controller_status_extension`). `"off"` and `"on"` must be quoted or YAML parses them as booleans.

```yaml
enums:
  ro_state:
    0: unknown
    1: standby
    2: startup_flush
    3: divert
    4: production
    5: shutdown_flush
    6: fault
    7: maintenance
  pump_commanded:
    0: "off"
    1: "on"
    2: unknown
  fault_severity:
    0: none
    1: advisory
    2: warning
    3: critical
controller_flags_bits: {}
fault_codes:
- {code: 0, source: controller, default_severity: none, description: No active fault}
- {code: 1001, source: controller, default_severity: critical, description: High RO feed pressure interlock}
- {code: 1002, source: controller, default_severity: critical, description: Concentrate flow below configured limit during production}
- {code: 1003, source: controller, default_severity: critical, description: Critical sensor data unavailable during production}
- {code: 1004, source: controller, default_severity: critical, description: High-high storage level / overflow interlock}
- {code: 1005, source: controller, default_severity: critical, description: RS485 sensor-node communications timeout during production}
- {code: 2001, source: controller, default_severity: warning, description: Membrane rejection below configured warning limit}
- {code: 2002, source: controller, default_severity: warning, description: Abnormal RO pressure trend}
- {code: 3001, source: controller, default_severity: advisory, description: Maintenance or calibration due}
- {code: 4001, source: sensor, default_severity: critical, state_dependent: true, description: Critical local measurement invalid or stale}
- {code: 4002, source: sensor, default_severity: warning, description: Sensor degraded / inconsistent readings}
- {code: 4003, source: sensor, default_severity: advisory, description: Controller status unavailable}
- {code: 4004, source: sensor, default_severity: advisory, description: LCD communication failure (log only when display absent)}
```

In the existing `holding_registers` list add one key to four entries, changing nothing else: address 220 gets `equals: 1`; 222 gets `enum: ro_state`; 223 gets `enum: pump_commanded`; 225 gets `enum: fault_severity`.

In `protocol/examples/sample_snapshot.json` change `"protocol_version": "1.0"` to `"1.1"`.

- [ ] **Step 3: Write failing schema tests**

`host_tools/tests/test_schema.py`:

```python
"""Tests for register-map loading and validation."""
import copy
from pathlib import Path

import pytest
import yaml

from ro_tools import schema


@pytest.fixture()
def raw() -> dict:
    return yaml.safe_load(schema.DEFAULT_MAP_PATH.read_text(encoding="utf-8"))


def _reg(raw: dict, table: str, name: str) -> dict:
    return next(r for r in raw[table] if r["name"] == name)


def test_real_map_loads():
    m = schema.load()
    assert (m.version_major, m.version_minor) == (1, 1)
    assert (m.input_start, m.input_count) == (100, 40)
    assert (m.status_start, m.status_count) == (220, 8)
    assert m.critical_validity_bits == (0, 1, 2, 3, 7)
    assert m.enums["ro_state"][4] == "production"
    assert m.enums["pump_commanded"] == {0: "off", 1: "on", 2: "unknown"}
    assert [r.address for r in m.input_registers] == sorted(r.address for r in m.input_registers)


def test_register_defaults_and_flags():
    m = schema.load()
    by_name = {r.name: r for r in m.input_registers + m.holding_registers}
    assert by_name["device_id"].scale_divisor == 1
    assert by_name["reserved_133"].reserved is True
    assert by_name["feed_ec_us_cm_x10"].reserved is False
    assert by_name["ro_state"].enum == "ro_state"
    assert by_name["status_schema_major"].equals == 1
    fc = {f.code: f for f in m.fault_codes}
    assert fc[4001].state_dependent is True
    assert fc[1001].state_dependent is False


def _mutations():
    def bad_type(r): _reg(r, "input_registers", "module_status")["type"] = "u8"
    def bad_words(r): _reg(r, "input_registers", "uptime_seconds")["words"] = 1
    def overlap(r): _reg(r, "input_registers", "validity_mask")["address"] = 103
    def gap(r): r["input_registers"] = [x for x in r["input_registers"] if x["name"] != "reserved_139"]
    def outside(r): _reg(r, "input_registers", "reserved_139")["address"] = 140
    def bad_scale(r): _reg(r, "input_registers", "feed_ec_us_cm_x10")["scale_divisor"] = 100
    def zero_scale(r): _reg(r, "input_registers", "module_status")["scale_divisor"] = 0
    def unsuffixed_scale(r): _reg(r, "input_registers", "module_status")["scale_divisor"] = 10
    def dup_name(r): _reg(r, "holding_registers", "device_id")["name"] = "module_status"
    def bad_identifier(r): _reg(r, "holding_registers", "device_id")["name"] = "device-id"
    def bit_range(r): r["status_bits"][16] = "too_high"
    def critical_not_subset(r): r["critical_validity_bits"].append(12)
    def ext_start(r): r["controller_status_extension"]["start"] = 221
    def ext_count(r): r["controller_status_extension"]["count"] = 7
    def bad_access(r): _reg(r, "holding_registers", "device_id")["access"] = "read_write"
    def bad_enum_ref(r): _reg(r, "holding_registers", "ro_state")["enum"] = "nope"
    def enum_value_range(r): r["enums"]["ro_state"][70000] = "huge"
    def dup_fault(r): r["fault_codes"].append(dict(r["fault_codes"][1]))
    def fault_source(r): r["fault_codes"][1]["source"] = "lcd"
    def fault_severity(r): r["fault_codes"][1]["default_severity"] = "fatal"
    def no_code_zero(r): r["fault_codes"] = r["fault_codes"][1:]
    def addressing(r): r["addressing"] = "one_based"
    def word_order(r): r["word_order_32bit"] = "low_word_first"
    def missing_key(r): del r["polling"]
    return [v for k, v in locals().items() if callable(v)]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_each_rule_rejects(raw, mutate):
    broken = copy.deepcopy(raw)
    mutate(broken)
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert exc.value.violations


def test_all_violations_reported_together(raw):
    broken = copy.deepcopy(raw)
    _reg(broken, "input_registers", "module_status")["type"] = "u8"
    broken["fault_codes"][1]["source"] = "lcd"
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert len(exc.value.violations) >= 2


def test_load_accepts_path(tmp_path: Path, raw):
    p = tmp_path / "map.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert schema.load(p).unit_id == 1
```

- [ ] **Step 4: Run to verify failure**

Run: `uv run pytest tests/test_schema.py -q`
Expected: collection error, `ImportError: cannot import name 'schema'`.

- [ ] **Step 5: Implement `schema.py`**

Implement the interface above. `parse` collects violations in a `list[str]` and raises one `SchemaError` at the end if non-empty; each message names the offending key or register. Rules, exactly:

1. Required top-level keys present: `protocol, version, unit_id, serial, addressing, word_order_32bit, byte_order_per_word, polling, validity_bits, critical_validity_bits, status_bits, fault_bits, input_registers, holding_registers, controller_status_extension, enums, controller_flags_bits, fault_codes`. If any is missing, raise immediately with those violations (later rules cannot run). `addressing == "zero_based_pdu_offset"`, `word_order_32bit == "high_word_first"`, `byte_order_per_word == "big_endian"`.
2. `type` in `{"u16","i16","u32","i32"}`; `words` (default 1) equals 1 for 16-bit and 2 for 32-bit types.
3. Within each table, no address occupied twice (a register occupies `address .. address+words-1`).
4. The set of addresses occupied by input registers equals `range(input_start, input_start + input_count)` exactly.
5. `scale_divisor` (default 1) is an `int >= 1`. If the name matches `_x(10|100|1000)$` the divisor equals that number; otherwise the divisor is 1.
6. Names unique across both tables; each satisfies `str.isidentifier()`.
7. Keys of `validity_bits`, `status_bits`, `fault_bits`, `controller_flags_bits` are ints in 0..15; `critical_validity_bits` is a subset of `validity_bits` keys.
8. Holding registers with access `write_multiple_only` occupy exactly `range(ext.start, ext.start + ext.count)`.
9. `access` in `{"read_only", "write_multiple_only"}`.
10. Every register `enum` names a key of `enums`; every enum value key is an int in 0..65535; member names within an enum are unique.
11. Fault codes: unique, int in 0..65535, `source` in `{"controller","sensor"}`, `default_severity` is a member name of `enums["fault_severity"]`; code 0 exists with `default_severity == "none"`.

- [ ] **Step 6: Run schema tests**

Run: `uv run pytest tests/test_schema.py tests/test_register_map.py -q`
Expected: all pass (24 parametrized mutation cases plus 5 others).

- [ ] **Step 7: Docs-consistency test**

`host_tools/tests/test_docs_consistency.py`:

```python
"""The YAML is normative; these tests fail when the markdown drifts from it."""
import re
from pathlib import Path

from ro_tools import schema

REPO = Path(__file__).resolve().parents[2]


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not set(line) <= set("|-: "):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def test_fault_catalog_matches_yaml():
    m = schema.load()
    text = (REPO / "docs/specs/FAULT_CODE_CATALOG.md").read_text(encoding="utf-8")
    rows = [r for r in _table_rows(text) if r[0].isdigit()]
    doc = {}
    for code, source, severity, description in rows:
        state_dependent = severity.endswith("when required")
        doc[int(code)] = (source, severity.split()[0], description, state_dependent)
    yaml_codes = {
        f.code: (f.source, f.default_severity, f.description, f.state_dependent)
        for f in m.fault_codes
    }
    assert doc == yaml_codes


def test_status_extension_table_matches_yaml():
    m = schema.load()
    text = (REPO / "protocol/CONTROLLER_STATUS_EXTENSION.md").read_text(encoding="utf-8")
    doc = {int(r[0]): r[1] for r in _table_rows(text) if r[0].isdigit()}
    ext = {
        r.address: r.name for r in m.holding_registers if r.access == "write_multiple_only"
    }
    assert doc == ext


def test_ro_states_match_yaml():
    m = schema.load()
    text = (REPO / "protocol/CONTROLLER_STATUS_EXTENSION.md").read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("RO states:"))
    sentence = line.split(".")[0]
    doc = {int(n): name for n, name in re.findall(r"(\d+)=(\w+)", sentence)}
    assert doc == m.enums["ro_state"]
```

Run: `uv run pytest tests/test_docs_consistency.py -q`
Expected: 3 passed. If one fails, the YAML addition in Step 2 has a typo; fix the YAML, not the markdown.

- [ ] **Step 8: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .` Expected: no errors.

```bash
git add -A host_tools protocol .gitignore
git commit -m "Add register-map schema validator and machine-readable enums"
```

---

### Task 2: Code generator and generated codec

**Files:**
- Create: `host_tools/src/ro_tools/codegen.py`, `host_tools/src/ro_tools/generated/__init__.py` (empty docstring module), `host_tools/src/ro_tools/generated/registers.py` (generator output)
- Test: `host_tools/tests/test_codegen.py`, `host_tools/tests/test_codec.py`

**Interfaces:**
- Consumes: `ro_tools.schema.load() -> RegisterMap`, `Register`, `FaultCode` (Task 1).
- Produces (`ro_tools.codegen`):

```python
GENERATED_PATH: Path   # Path(__file__).resolve().parent / "generated" / "registers.py"
def render(m: RegisterMap) -> str: ...            # deterministic; ends with exactly one "\n"
def write(m: RegisterMap, path: Path = GENERATED_PATH) -> None: ...   # newline="\n", utf-8
def is_current(m: RegisterMap, path: Path = GENERATED_PATH) -> bool: ...
```

- Produces (`ro_tools.generated.registers`), everything later tasks use:

```python
PROTOCOL_MAJOR = 1; PROTOCOL_MINOR = 1; UNIT_ID = 1
SERIAL_BAUD = 19200; SERIAL_DATA_BITS = 8; SERIAL_PARITY = "E"; SERIAL_STOP_BITS = 1
INPUT_START = 100; INPUT_COUNT = 40
POLL_PERIOD_MS = 1000; CRITICAL_MAX_AGE_MS = 3000; CLIENT_LOSS_TIMEOUT_MS = 3000
STATUS_START = 220; STATUS_COUNT = 8; STATUS_TIMEOUT_MS = 3000; STATUS_SCHEMA_MAJOR = 1
METADATA_START = 200; METADATA_COUNT = 3        # the read_only holding registers
ADDR_<UPPER_NAME> = <address>                   # one per register in both tables, incl. reserved
TYPE_RANGES = {"u16": (0, 65535), "i16": (-32768, 32767), "u32": (0, 4294967295), "i32": (-2147483648, 2147483647)}
class ValidityBits(IntFlag)   # FEED_EC = 1 << 0, ... upper-cased YAML names
CRITICAL_VALIDITY = ValidityBits(0x008F)
class StatusBits(IntFlag); class FaultBits(IntFlag); class ControllerFlags(IntFlag)
CONTROLLER_FLAGS_DEFINED_MASK = 0
class RoState(IntEnum); class PumpCommanded(IntEnum); class FaultSeverity(IntEnum)   # upper-cased member names
@dataclass(frozen=True) class FaultCodeInfo: code: int; source: str; default_severity: FaultSeverity; description: str; state_dependent: bool
FAULT_CODES: dict[int, FaultCodeInfo]
SNAPSHOT_LAYOUT: tuple[tuple[str, str, int], ...]   # (field name, type, word offset from INPUT_START); reserved registers excluded
STATUS_LAYOUT: tuple[tuple[str, str, int], ...]     # same shape, offsets from STATUS_START
METADATA_LAYOUT: tuple[tuple[str, str, int], ...]   # offsets from METADATA_START
@dataclass(frozen=True) class Snapshot      # one int field per SNAPSHOT_LAYOUT entry, in order, each defaulting to 0;
                                            # a float property per scaled field named without the _xN suffix
@dataclass(frozen=True) class ControllerStatus   # status_schema_major: int = 1, the other seven fields default 0
class StatusValidationError(ValueError)
def encode_snapshot(s: Snapshot) -> list[int]      # INPUT_COUNT words
def decode_snapshot(words: Sequence[int]) -> Snapshot
def encode_status(s: ControllerStatus) -> list[int]   # STATUS_COUNT words; range-checks only
def decode_status(words: Sequence[int]) -> ControllerStatus
def validate_status(words: Sequence[int]) -> None  # raises StatusValidationError
```

`SERIAL_PARITY` maps YAML `even/odd/none` to `"E"/"O"/"N"`.

- [ ] **Step 1: Write failing codec tests**

`host_tools/tests/test_codec.py`:

```python
"""Tests for the generated register codec."""
import dataclasses

import pytest
from hypothesis import given, strategies as st

from ro_tools.generated import registers as reg


def _field_strategy():
    return st.fixed_dictionaries(
        {name: st.integers(*reg.TYPE_RANGES[typ]) for name, typ, _ in reg.SNAPSHOT_LAYOUT}
    )


@given(_field_strategy())
def test_snapshot_round_trip(fields):
    s = reg.Snapshot(**fields)
    words = reg.encode_snapshot(s)
    assert len(words) == reg.INPUT_COUNT
    assert all(0 <= w <= 0xFFFF for w in words)
    assert reg.decode_snapshot(words) == s


def test_constants_match_map():
    assert (reg.INPUT_START, reg.INPUT_COUNT) == (100, 40)
    assert (reg.STATUS_START, reg.STATUS_COUNT) == (220, 8)
    assert reg.ADDR_FEED_EC_US_CM_X10 == 109
    assert reg.ADDR_RESERVED_139 == 139
    assert reg.SERIAL_PARITY == "E"
    assert int(reg.CRITICAL_VALIDITY) == 0x008F
    assert reg.RoState.PRODUCTION == 4
    assert reg.PumpCommanded.ON == 1
    assert reg.FaultSeverity.CRITICAL == 3
    assert reg.FAULT_CODES[4001].state_dependent is True
    assert reg.FAULT_CODES[1001].default_severity is reg.FaultSeverity.CRITICAL


def test_u32_is_high_word_first():
    words = reg.encode_snapshot(reg.Snapshot(uptime_seconds=0x12345678))
    off = reg.ADDR_UPTIME_SECONDS - reg.INPUT_START
    assert words[off : off + 2] == [0x1234, 0x5678]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-32768, 0x8000), (-1, 0xFFFF), (0, 0), (32767, 0x7FFF)],
)
def test_i16_twos_complement(value, expected):
    words = reg.encode_snapshot(reg.Snapshot(permeate_temp_c_x100=value))
    off = reg.ADDR_PERMEATE_TEMP_C_X100 - reg.INPUT_START
    assert words[off] == expected
    assert reg.decode_snapshot(words).permeate_temp_c_x100 == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-2147483648, [0x8000, 0]), (-1, [0xFFFF, 0xFFFF]), (0, [0, 0]), (2147483647, [0x7FFF, 0xFFFF])],
)
def test_i32_twos_complement(value, expected):
    words = reg.encode_snapshot(reg.Snapshot(load_left_raw=value))
    off = reg.ADDR_LOAD_LEFT_RAW - reg.INPUT_START
    assert words[off : off + 2] == expected
    assert reg.decode_snapshot(words).load_left_raw == value


@pytest.mark.parametrize(
    "kwargs",
    [{"module_status": 65536}, {"module_status": -1}, {"permeate_temp_c_x100": 32768},
     {"uptime_seconds": 2**32}, {"load_left_raw": -(2**31) - 1}],
)
def test_encode_overflow_raises(kwargs):
    with pytest.raises(ValueError):
        reg.encode_snapshot(reg.Snapshot(**kwargs))


@pytest.mark.parametrize("n", [0, 39, 41])
def test_decode_wrong_length_raises(n):
    with pytest.raises(ValueError):
        reg.decode_snapshot([0] * n)


def test_decode_rejects_non_u16_word():
    with pytest.raises(ValueError):
        reg.decode_snapshot([0] * 39 + [70000])


def test_reserved_words_ignored_on_decode_and_zero_on_encode():
    words = [0] * reg.INPUT_COUNT
    words[reg.ADDR_RESERVED_139 - reg.INPUT_START] = 0xBEEF
    s = reg.decode_snapshot(words)
    assert reg.encode_snapshot(s)[reg.ADDR_RESERVED_139 - reg.INPUT_START] == 0
    assert not any(f.name.startswith("reserved") for f in dataclasses.fields(s))


def test_scaled_properties():
    s = reg.Snapshot(feed_ec_us_cm_x10=4257, permeate_ec_us_cm_x100=1830,
                     permeate_flow_gpm_x1000=350, permeate_temp_c_x100=-250)
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert s.permeate_ec_us_cm == pytest.approx(18.3)
    assert s.permeate_flow_gpm == pytest.approx(0.35)
    assert s.permeate_temp_c == pytest.approx(-2.5)


def test_snapshot_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        reg.Snapshot().module_status = 1  # type: ignore[misc]


GOOD = [1, 7, int(reg.RoState.PRODUCTION), int(reg.PumpCommanded.ON), 0, 0, 0, 0]


def test_status_round_trip_and_valid():
    reg.validate_status(GOOD)
    s = reg.decode_status(GOOD)
    assert s.ro_state == 4 and s.status_sequence == 7
    assert reg.encode_status(s) == GOOD


def test_status_accepts_unknown_fault_code():
    reg.validate_status([1, 0, 6, 0, 9999, 3, 1, 0])


@pytest.mark.parametrize(
    "words",
    [
        GOOD[:7],                              # short
        GOOD + [0],                            # long
        [2] + GOOD[1:],                        # schema major
        [1, 0, 8, 0, 0, 0, 0, 0],              # ro_state out of enum
        [1, 0, 1, 3, 0, 0, 0, 0],              # pump_commanded out of enum
        [1, 0, 6, 0, 1001, 4, 1, 0],           # severity out of enum
        [1, 0, 1, 0, 0, 0, 0, 1],              # reserved flag bit set
        [1, 0, 6, 0, 1001, 0, 1, 0],           # code set, severity none
        [1, 0, 6, 0, 0, 3, 1, 0],              # severity set, code zero
        [1, 0, 6, 0, 1001, 3, 0, 0],           # code set, count zero
        [1, 0, 1, 0, 0, 0, 2, 0],              # count set, no fault
        [1, 70000, 1, 0, 0, 0, 0, 0],          # word out of u16
    ],
)
def test_status_rejects(words):
    with pytest.raises(reg.StatusValidationError):
        reg.validate_status(words)
```

`host_tools/tests/test_codegen.py`:

```python
"""Tests for the code generator itself."""
from ro_tools import codegen, schema


def test_render_is_deterministic():
    m = schema.load()
    assert codegen.render(m) == codegen.render(m)


def test_committed_file_matches_fresh_generation():
    assert codegen.is_current(schema.load()), "run: uv run python -m ro_tools.codegen"


def test_render_has_header_and_compiles():
    text = codegen.render(schema.load())
    assert text.startswith('"""GENERATED by ro_tools.codegen')
    assert "DO NOT EDIT" in text.splitlines()[0] + text.splitlines()[1] + text.splitlines()[2]
    assert text.endswith("\n") and not text.endswith("\n\n")
    compile(text, "registers.py", "exec")


def test_write_then_is_current(tmp_path):
    m = schema.load()
    out = tmp_path / "registers.py"
    assert not codegen.is_current(m, out)
    codegen.write(m, out)
    assert codegen.is_current(m, out)
    assert b"\r\n" not in out.read_bytes()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_codec.py tests/test_codegen.py -q`
Expected: collection errors (`No module named 'ro_tools.generated'`, `cannot import name 'codegen'`).

- [ ] **Step 3: Implement `codegen.py`**

`render` builds the module as a list of lines joined with `"\n"`. Emit data sections from the model, then a fixed codec body that is table-driven so it needs no per-field code. The emitted codec body is exactly:

```python
def _check(name: str, typ: str, value: int) -> None:
    lo, hi = TYPE_RANGES[typ]
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name}={value!r} out of range for {typ}")


def _encode(obj: object, layout: tuple[tuple[str, str, int], ...], count: int) -> list[int]:
    words = [0] * count
    for name, typ, offset in layout:
        value = getattr(obj, name)
        _check(name, typ, value)
        if typ in ("u32", "i32"):
            value &= 0xFFFFFFFF
            words[offset] = value >> 16
            words[offset + 1] = value & 0xFFFF
        else:
            words[offset] = value & 0xFFFF
    return words


def _decode(words: Sequence[int], layout: tuple[tuple[str, str, int], ...], count: int) -> dict[str, int]:
    if len(words) != count:
        raise ValueError(f"expected {count} words, got {len(words)}")
    for w in words:
        _check("word", "u16", w)
    out: dict[str, int] = {}
    for name, typ, offset in layout:
        if typ in ("u32", "i32"):
            value = (words[offset] << 16) | words[offset + 1]
            if typ == "i32" and value >= 0x80000000:
                value -= 0x100000000
        else:
            value = words[offset]
            if typ == "i16" and value >= 0x8000:
                value -= 0x10000
        out[name] = value
    return out


def encode_snapshot(s: Snapshot) -> list[int]:
    """Encode a snapshot to INPUT_COUNT register words; reserved words are zero."""
    return _encode(s, SNAPSHOT_LAYOUT, INPUT_COUNT)


def decode_snapshot(words: Sequence[int]) -> Snapshot:
    """Decode INPUT_COUNT register words. Makes no validity or freshness judgement."""
    return Snapshot(**_decode(words, SNAPSHOT_LAYOUT, INPUT_COUNT))


def encode_status(s: ControllerStatus) -> list[int]:
    """Encode a controller status block to STATUS_COUNT register words."""
    return _encode(s, STATUS_LAYOUT, STATUS_COUNT)


def decode_status(words: Sequence[int]) -> ControllerStatus:
    """Decode STATUS_COUNT register words without validating field values."""
    return ControllerStatus(**_decode(words, STATUS_LAYOUT, STATUS_COUNT))


def validate_status(words: Sequence[int]) -> None:
    """Raise StatusValidationError unless words form an acceptable status block."""
    try:
        s = decode_status(words)
    except ValueError as exc:
        raise StatusValidationError(str(exc)) from exc
    for name, allowed in _STATUS_ALLOWED:
        if getattr(s, name) not in allowed:
            raise StatusValidationError(f"{name}={getattr(s, name)} not permitted")
    if s.controller_flags & ~CONTROLLER_FLAGS_DEFINED_MASK:
        raise StatusValidationError("reserved controller_flags bit set")
    none = (s.controller_fault_code == 0, s.controller_fault_severity == 0, s.controller_fault_count == 0)
    if any(none) and not all(none):
        raise StatusValidationError("fault code, severity and count are inconsistent")
```

`_STATUS_ALLOWED` is emitted from the model as a tuple of `(field_name, frozenset_of_ints)`: for a register with `equals`, the single value; for a register with `enum`, that enum's keys. For the current map it is `(("status_schema_major", frozenset({1})), ("ro_state", frozenset({0,...,7})), ("pump_commanded", frozenset({0,1,2})), ("controller_fault_severity", frozenset({0,1,2,3})))` with sorted set contents so output is deterministic.

Other emission rules:
- First three lines: `"""GENERATED by ro_tools.codegen from protocol/register_map.yaml (protocol 1.1).`, blank, `DO NOT EDIT. Regenerate with: uv run ro-tools generate"""`. Then `from __future__ import annotations`, and imports `Sequence` from `collections.abc`, `dataclass` from `dataclasses`, `IntEnum, IntFlag` from `enum`.
- Enum/flag member names are the YAML names upper-cased. A flag class with no members is emitted with a docstring body only.
- `Snapshot` property for a scaled field: name is the field name with the `_x10|_x100|_x1000` suffix removed, body `return self.<field> / <divisor>`, return type `float`.
- `render` raises `ValueError` if the status block lacks any of `controller_fault_code`, `controller_fault_severity`, `controller_fault_count`, `controller_flags`, because the fixed `validate_status` body references them.
- `METADATA_START`/`METADATA_COUNT` are the lowest address and the count of `read_only` holding registers.
- `write` uses `path.write_text(text, encoding="utf-8", newline="\n")`. `is_current` returns `path.exists() and path.read_text(encoding="utf-8") == render(m)`.
- Add `if __name__ == "__main__": write(schema.load())` so `uv run python -m ro_tools.codegen` regenerates.

- [ ] **Step 4: Generate**

Run: `uv run python -m ro_tools.codegen`
Expected: creates `src/ro_tools/generated/registers.py`. Create `src/ro_tools/generated/__init__.py` with a one-line docstring.

- [ ] **Step 5: Run tests**

Run: `uv run pytest -q`
Expected: all pass, including Task 1 tests.

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .` (the generated directory is excluded). Re-run `uv run pytest tests/test_codegen.py -q` to confirm formatting did not touch the generated file.

```bash
git add -A host_tools
git commit -m "Add register codegen and generated typed codec"
```

---

### Task 3: Register bank

**Files:**
- Create: `host_tools/src/ro_tools/sim/__init__.py` (one-line docstring), `host_tools/src/ro_tools/sim/register_bank.py`
- Test: `host_tools/tests/test_register_bank.py`

**Interfaces:**
- Consumes: `ro_tools.generated.registers` (Task 2): `Snapshot`, `ControllerStatus`, `encode_snapshot`, `decode_status`, `validate_status`, `StatusValidationError`, `SNAPSHOT_LAYOUT`, `TYPE_RANGES`, `StatusBits`, `INPUT_START`, `INPUT_COUNT`, `STATUS_START`, `STATUS_COUNT`, `METADATA_START`, `METADATA_COUNT`, `PROTOCOL_MAJOR`, `PROTOCOL_MINOR`.
- Produces (`ro_tools.sim.register_bank`):

```python
EXC_ILLEGAL_FUNCTION = 0x01
EXC_ILLEGAL_ADDRESS = 0x02
EXC_ILLEGAL_VALUE = 0x03

class RegisterBank:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 metadata: tuple[int, int, int] = (1, 0, 1)) -> None: ...
        # clock returns seconds. metadata = (configuration_schema_version, calibration_revision, device_id).
        # A new bank publishes an all-zero snapshot except protocol_major/minor and sample_interval_ms=1000:
        # sequence 0, validity 0, module_status 0. Nothing is valid until a test or preset says so.
    def set_field(self, name: str, raw: int) -> None: ...   # pending; KeyError for unknown name, ValueError if out of type range
    def set_validity(self, bits: int) -> None: ...          # pending validity_mask
    def set_faults(self, bits: int) -> None: ...            # pending fault_mask
    def set_status(self, bits: int) -> None: ...            # pending module_status
    def freeze_sequence(self, on: bool) -> None: ...
    def force_critical_age(self, ms: int) -> None: ...      # pending critical_age_ms = min(ms, 65535); ValueError if ms < 0
    def saturate(self, name: str) -> None: ...              # pending field = type maximum; ORs StatusBits.OVERFLOW_OR_SATURATION into pending module_status
    def commit(self) -> None: ...                           # publish pending; sequence += 1 mod 65536 unless frozen; uptime_seconds = int(clock() - boot time)
    def reboot(self) -> None: ...                           # see Step 3
    def published(self) -> Snapshot: ...
    @property
    def controller_status(self) -> ControllerStatus | None: ...     # None until a valid FC16 write, and again after reboot()
    @property
    def last_valid_status_received_ms(self) -> int | None: ...      # int(clock() * 1000) at the last valid write
    def handle_pdu(self, pdu: bytes) -> bytes: ...          # always returns a response PDU, normal or exception
```

- [ ] **Step 1: Write failing tests**

`host_tools/tests/test_register_bank.py`:

```python
"""Tests for the pure simulated register bank."""
import struct
import threading

import pytest

from ro_tools.generated import registers as reg
from ro_tools.sim.register_bank import (
    EXC_ILLEGAL_ADDRESS,
    EXC_ILLEGAL_FUNCTION,
    EXC_ILLEGAL_VALUE,
    RegisterBank,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def bank(clock) -> RegisterBank:
    return RegisterBank(clock=clock)


def read(fc: int, addr: int, count: int) -> bytes:
    return struct.pack(">BHH", fc, addr, count)


def write16(addr: int, values: list[int]) -> bytes:
    return struct.pack(">BHHB", 16, addr, len(values), 2 * len(values)) + struct.pack(
        f">{len(values)}H", *values
    )


def words_of(resp: bytes) -> list[int]:
    assert resp[0] < 0x80, f"exception response {resp.hex()}"
    assert resp[1] == len(resp) - 2
    return list(struct.unpack(f">{resp[1] // 2}H", resp[2:]))


def exc(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


GOOD = [1, 5, 4, 1, 0, 0, 0, 0]


def test_new_bank_publishes_nothing_valid(bank):
    s = bank.published()
    assert (s.protocol_major, s.protocol_minor) == (reg.PROTOCOL_MAJOR, reg.PROTOCOL_MINOR)
    assert s.validity_mask == 0 and s.module_status == 0 and s.snapshot_sequence == 0


def test_fc04_full_block_decodes(bank):
    bank.set_field("feed_ec_us_cm_x10", 4257)
    bank.commit()
    s = reg.decode_snapshot(words_of(bank.handle_pdu(read(4, 100, 40))))
    assert s.feed_ec_us_cm_x10 == 4257 and s.snapshot_sequence == 1


def test_fc04_subrange(bank):
    bank.set_field("module_status", 0x0001)
    bank.commit()
    assert words_of(bank.handle_pdu(read(4, 103, 1))) == [1]


@pytest.mark.parametrize(("addr", "count"), [(99, 1), (100, 41), (139, 2), (140, 1), (0, 1), (200, 1)])
def test_fc04_outside_block_is_illegal_address(bank, addr, count):
    assert bank.handle_pdu(read(4, addr, count)) == exc(4, EXC_ILLEGAL_ADDRESS)


def test_fc03_metadata(bank):
    assert words_of(bank.handle_pdu(read(3, 200, 3))) == [1, 0, 1]


def test_fc03_status_block_is_zero_before_first_write(bank):
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == [0] * 8
    assert bank.controller_status is None
    assert bank.last_valid_status_received_ms is None


@pytest.mark.parametrize(("addr", "count"), [(199, 1), (200, 4), (203, 1), (219, 2), (220, 9), (228, 1), (202, 19), (100, 1)])
def test_fc03_outside_ranges_is_illegal_address(bank, addr, count):
    assert bank.handle_pdu(read(3, addr, count)) == exc(3, EXC_ILLEGAL_ADDRESS)


@pytest.mark.parametrize("count", [0, 126])
def test_read_bad_quantity_is_illegal_value(bank, count):
    assert bank.handle_pdu(read(4, 100, count)) == exc(4, EXC_ILLEGAL_VALUE)


def test_fc16_valid_write_accepted(bank, clock):
    clock.t = 123.456
    assert bank.handle_pdu(write16(220, GOOD)) == struct.pack(">BHH", 16, 220, 8)
    assert bank.controller_status == reg.decode_status(GOOD)
    assert bank.last_valid_status_received_ms == 123456
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == GOOD


def test_fc16_unknown_fault_code_accepted(bank):
    words = [1, 0, 6, 0, 9999, 3, 1, 0]
    assert bank.handle_pdu(write16(220, words))[0] == 16
    assert bank.controller_status.controller_fault_code == 9999


@pytest.mark.parametrize(
    ("addr", "values"),
    [(220, GOOD[:7]), (221, GOOD[:7]), (220, GOOD + [0]), (219, [0] + GOOD), (222, [4]),
     (200, [1]), (200, [1, 0, 1]), (202, [1] * 26), (100, [0] * 8)],
)
def test_fc16_wrong_range_is_illegal_address_and_preserves_status(bank, clock, addr, values):
    bank.handle_pdu(write16(220, GOOD))
    before = (bank.controller_status, bank.last_valid_status_received_ms)
    clock.t += 1
    assert bank.handle_pdu(write16(addr, values)) == exc(16, EXC_ILLEGAL_ADDRESS)
    assert (bank.controller_status, bank.last_valid_status_received_ms) == before


@pytest.mark.parametrize(
    "values",
    [[2, 5, 4, 1, 0, 0, 0, 0], [1, 5, 8, 1, 0, 0, 0, 0], [1, 5, 4, 3, 0, 0, 0, 0],
     [1, 5, 6, 0, 1001, 4, 1, 0], [1, 5, 4, 1, 0, 0, 0, 1], [1, 5, 6, 0, 1001, 0, 1, 0]],
)
def test_fc16_bad_value_is_illegal_value_and_preserves_status(bank, clock, values):
    bank.handle_pdu(write16(220, GOOD))
    before = (bank.controller_status, bank.last_valid_status_received_ms)
    clock.t += 1
    assert bank.handle_pdu(write16(220, values)) == exc(16, EXC_ILLEGAL_VALUE)
    assert (bank.controller_status, bank.last_valid_status_received_ms) == before


def test_fc16_malformed_byte_count_is_illegal_value(bank):
    pdu = struct.pack(">BHHB", 16, 220, 8, 15) + b"\x00" * 16
    assert bank.handle_pdu(pdu) == exc(16, EXC_ILLEGAL_VALUE)
    assert bank.handle_pdu(write16(220, GOOD)[:-1]) == exc(16, EXC_ILLEGAL_VALUE)


@pytest.mark.parametrize("fc", [1, 2, 5, 6, 15, 22, 23, 43, 0x7F])
def test_other_function_codes_are_illegal_function(bank, fc):
    assert bank.handle_pdu(bytes([fc, 0, 220, 0, 1])) == exc(fc, EXC_ILLEGAL_FUNCTION)


def test_truncated_read_request_is_illegal_value(bank):
    assert bank.handle_pdu(bytes([4, 0, 100])) == exc(4, EXC_ILLEGAL_VALUE)


def test_pending_not_visible_until_commit(bank):
    bank.commit()
    bank.set_field("feed_ec_us_cm_x10", 999)
    assert bank.published().feed_ec_us_cm_x10 == 0
    bank.commit()
    assert bank.published().feed_ec_us_cm_x10 == 999


def test_sequence_rolls_over(bank):
    bank.set_field("snapshot_sequence", 65535)
    bank.freeze_sequence(True)
    bank.commit()
    assert bank.published().snapshot_sequence == 65535
    bank.freeze_sequence(False)
    bank.commit()
    assert bank.published().snapshot_sequence == 0


def test_frozen_sequence_does_not_advance(bank):
    bank.commit()
    bank.freeze_sequence(True)
    bank.commit()
    bank.commit()
    assert bank.published().snapshot_sequence == 1


def test_uptime_follows_clock(bank, clock):
    clock.t += 42.9
    bank.commit()
    assert bank.published().uptime_seconds == 42


def test_force_critical_age_saturates(bank):
    bank.force_critical_age(70000)
    bank.commit()
    assert bank.published().critical_age_ms == 65535
    with pytest.raises(ValueError):
        bank.force_critical_age(-1)


def test_saturate_sets_max_and_flag(bank):
    bank.saturate("permeate_total_pulses")
    bank.commit()
    s = bank.published()
    assert s.permeate_total_pulses == 0xFFFFFFFF
    assert s.module_status & reg.StatusBits.OVERFLOW_OR_SATURATION


def test_set_field_rejects_unknown_and_out_of_range(bank):
    with pytest.raises(KeyError):
        bank.set_field("nope", 1)
    with pytest.raises(ValueError):
        bank.set_field("module_status", 70000)


def test_mask_setters(bank):
    bank.set_validity(0x008F)
    bank.set_faults(0x0100)
    bank.set_status(0x0001)
    bank.commit()
    s = bank.published()
    assert (s.validity_mask, s.fault_mask, s.module_status) == (0x008F, 0x0100, 0x0001)


def test_reboot_discontinuity(bank, clock):
    bank.set_field("feed_ec_us_cm_x10", 4257)
    bank.commit()
    bank.commit()
    bank.handle_pdu(write16(220, GOOD))
    clock.t += 500
    bank.reboot()
    s = bank.published()
    assert s.boot_counter == 1
    assert s.uptime_seconds == 0
    assert s.snapshot_sequence == 0
    assert s.module_status & reg.StatusBits.WATCHDOG_RESET_SEEN
    assert s.feed_ec_us_cm_x10 == 4257
    assert bank.controller_status is None
    assert bank.last_valid_status_received_ms is None
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == [0] * 8


def test_reader_never_sees_mixed_snapshot(bank):
    stop = threading.Event()

    def writer() -> None:
        v = 0
        while not stop.is_set():
            v = (v + 1) % 1000
            for name in ("feed_ec_us_cm_x10", "permeate_ec_us_cm_x100", "ro_feed_pressure_psi_x10"):
                bank.set_field(name, v)
            bank.commit()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(3000):
            s = reg.decode_snapshot(words_of(bank.handle_pdu(read(4, 100, 40))))
            assert s.feed_ec_us_cm_x10 == s.permeate_ec_us_cm_x100 == s.ro_feed_pressure_psi_x10
    finally:
        stop.set()
        t.join()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_register_bank.py -q`
Expected: collection error, `No module named 'ro_tools.sim'`.

- [ ] **Step 3: Implement `register_bank.py`**

State: `self._lock = threading.Lock()`; `self._pending: dict[str, int]` keyed by every `SNAPSHOT_LAYOUT` name; `self._published: Snapshot`; `self._frozen: bool`; `self._boot_time: float`; `self._metadata: list[int]`; `self._status_words: list[int]` (8 zeros); `self._status: ControllerStatus | None`; `self._status_rx_ms: int | None`. Every public method takes the lock.

`commit()`: unless frozen, `pending["snapshot_sequence"] = (pending["snapshot_sequence"] + 1) % 65536`; `pending["uptime_seconds"] = int(clock() - boot_time)`; `published = Snapshot(**pending)`.

`reboot()`: `boot_counter += 1`; `boot_time = clock()`; `uptime_seconds = 0`; `snapshot_sequence = 0`; OR `StatusBits.WATCHDOG_RESET_SEEN` into `module_status`; clear status words to zeros, `_status = None`, `_status_rx_ms = None`; publish directly without advancing the sequence. Measurement fields are left as they were.

`handle_pdu(pdu)`, with `fc = pdu[0]` (an empty PDU returns `bytes([0x80, EXC_ILLEGAL_FUNCTION])`):

```python
if fc not in (3, 4, 16):
    return bytes([fc | 0x80, EXC_ILLEGAL_FUNCTION])
if fc in (3, 4):
    if len(pdu) != 5:
        return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
    addr, count = struct.unpack(">HH", pdu[1:])
    if not 1 <= count <= 125:
        return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
    end = addr + count
    if fc == 4:
        if addr < INPUT_START or end > INPUT_START + INPUT_COUNT:
            return bytes([fc | 0x80, EXC_ILLEGAL_ADDRESS])
        words = encode_snapshot(self._published)[addr - INPUT_START : end - INPUT_START]
    elif METADATA_START <= addr and end <= METADATA_START + METADATA_COUNT:
        words = self._metadata[addr - METADATA_START : end - METADATA_START]
    elif STATUS_START <= addr and end <= STATUS_START + STATUS_COUNT:
        words = self._status_words[addr - STATUS_START : end - STATUS_START]
    else:
        return bytes([fc | 0x80, EXC_ILLEGAL_ADDRESS])
    return bytes([fc, 2 * len(words)]) + struct.pack(f">{len(words)}H", *words)
# fc == 16
if len(pdu) < 6:
    return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
addr, count, byte_count = struct.unpack(">HHB", pdu[1:6])
if not 1 <= count <= 123 or byte_count != 2 * count or len(pdu) != 6 + byte_count:
    return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
if (addr, count) != (STATUS_START, STATUS_COUNT):
    return bytes([fc | 0x80, EXC_ILLEGAL_ADDRESS])
values = list(struct.unpack(f">{count}H", pdu[6:]))
try:
    validate_status(values)
except StatusValidationError:
    return bytes([fc | 0x80, EXC_ILLEGAL_VALUE])
self._status_words = values
self._status = decode_status(values)
self._status_rx_ms = int(self._clock() * 1000)
return struct.pack(">BHH", 16, addr, count)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .`

```bash
git add -A host_tools
git commit -m "Add simulated sensor-node register bank with fault injection"
```

---

### Task 4: Framing, responder, TCP and serial transports, presets

**Files:**
- Create: `host_tools/src/ro_tools/sim/frames.py`, `host_tools/src/ro_tools/sim/server.py`, `host_tools/src/ro_tools/sim/presets.py`
- Test: `host_tools/tests/test_frames.py`, `host_tools/tests/test_server.py`

**Interfaces:**
- Consumes: `RegisterBank` with `handle_pdu(pdu: bytes) -> bytes`, setters, `commit()` (Task 3); `ro_tools.generated.registers` constants, `ValidityBits`, `StatusBits`, `FaultBits`, `CRITICAL_VALIDITY` (Task 2).
- Produces:

```python
# ro_tools.sim.frames
class FrameError(ValueError): ...
def crc16(data: bytes) -> int: ...                       # Modbus CRC-16 (poly 0xA001, init 0xFFFF)
def build_rtu(unit: int, pdu: bytes) -> bytes: ...       # unit + pdu + CRC low byte + CRC high byte
def parse_rtu(frame: bytes) -> tuple[int, bytes]: ...    # (unit, pdu); FrameError if len < 4 or CRC mismatch
def build_mbap(transaction: int, unit: int, pdu: bytes) -> bytes: ...
def parse_mbap_header(header: bytes) -> tuple[int, int, int]: ...   # (transaction, remaining_length, unit); FrameError if len != 7, protocol id != 0, or remaining_length not in 2..254

# ro_tools.sim.server
class Responder:
    def __init__(self, bank: RegisterBank, unit_id: int = UNIT_ID) -> None: ...
    bank: RegisterBank
    unit_id: int
    drop_responses: bool          # default False
    delay_s: float                # default 0.0
    request_count: int            # requests addressed to unit_id, including dropped ones
    def respond(self, unit: int, pdu: bytes) -> bytes | None: ...   # None = send nothing

class TcpSimServer:
    def __init__(self, responder: Responder, host: str = "127.0.0.1", port: int = 0) -> None: ...
    address: tuple[str, int]      # actual bound address, valid after construction
    def start(self) -> None: ...  # daemon thread
    def stop(self) -> None: ...
    def __enter__(self) -> "TcpSimServer": ...   # calls start()
    def __exit__(self, *exc) -> None: ...        # calls stop()

class SerialLike(Protocol):
    def read(self, size: int = 1) -> bytes: ...   # returns b"" on timeout
    def write(self, data: bytes) -> int | None: ...

def serve_rtu_on(responder: Responder, port: SerialLike, stop: threading.Event) -> None: ...
def serve_rtu(responder: Responder, device: str, stop: threading.Event, *, baud: int = SERIAL_BAUD,
              parity: str = SERIAL_PARITY, stop_bits: int = SERIAL_STOP_BITS) -> None: ...

# ro_tools.sim.presets
PRESETS: tuple[str, ...] = ("healthy", "critical_sensor_invalid", "stale", "frozen_sequence", "silent")
def apply_preset(responder: Responder, name: str) -> None: ...   # ValueError for an unknown name; commits the bank
```

- [ ] **Step 1: Write failing frame tests**

`host_tools/tests/test_frames.py`:

```python
"""Wire-format tests, cross-checked against pymodbus."""
import pytest
from pymodbus.framer import FramerRTU

from ro_tools.sim import frames


def test_crc_known_vector():
    # Standard published example: 01 03 00 00 00 0A -> C5 CD on the wire.
    assert frames.build_rtu(1, bytes.fromhex("0300000 00A".replace(" ", ""))) == bytes.fromhex("01030000000AC5CD")


def test_input_block_request_bytes():
    frame = frames.build_rtu(1, bytes([4]) + (100).to_bytes(2, "big") + (40).to_bytes(2, "big"))
    assert frame[:6] == bytes.fromhex("010400640028")   # zero-based address 100, count 40
    assert len(frame) == 8


@pytest.mark.parametrize("payload", [b"\x01\x04\x00\x64\x00\x28", b"\x01\x10\x00\xdc\x00\x08\x10" + bytes(16), b"\x00"])
def test_crc_agrees_with_pymodbus(payload):
    # pymodbus returns the CRC already byte-swapped into wire order.
    assert frames.build_rtu(payload[0], payload[1:])[-2:] == FramerRTU.compute_CRC(payload).to_bytes(2, "big")


def test_parse_rtu_round_trip():
    assert frames.parse_rtu(frames.build_rtu(1, b"\x04\x00\x64\x00\x28")) == (1, b"\x04\x00\x64\x00\x28")


def test_parse_rtu_rejects_corrupt_crc():
    frame = bytearray(frames.build_rtu(1, b"\x04\x00\x64\x00\x28"))
    frame[3] ^= 0x01
    with pytest.raises(frames.FrameError):
        frames.parse_rtu(bytes(frame))


@pytest.mark.parametrize("frame", [b"", b"\x01", b"\x01\x04\x00"])
def test_parse_rtu_rejects_short(frame):
    with pytest.raises(frames.FrameError):
        frames.parse_rtu(frame)


def test_mbap_round_trip():
    adu = frames.build_mbap(0x1234, 1, b"\x04\x00\x64\x00\x28")
    assert adu[:7] == bytes.fromhex("12340000000601")
    assert frames.parse_mbap_header(adu[:7]) == (0x1234, 6, 1)


@pytest.mark.parametrize("header", [b"\x00" * 6, bytes.fromhex("00010001000601"), bytes.fromhex("00010000000101"), bytes.fromhex("000100000100 01".replace(" ", ""))])
def test_mbap_rejects_bad_header(header):
    with pytest.raises(frames.FrameError):
        frames.parse_mbap_header(header)
```

If `test_crc_agrees_with_pymodbus` fails only because pymodbus returns the CRC in the opposite byte order, change `"big"` to `"little"` in that one assertion; `test_crc_known_vector` is the authority for wire order.

- [ ] **Step 2: Write failing server tests**

`host_tools/tests/test_server.py`:

```python
"""Tests for the responder, transports and presets (raw sockets, no pymodbus)."""
import socket
import struct
import threading
import time

import pytest

from ro_tools.generated import registers as reg
from ro_tools.sim import frames
from ro_tools.sim.presets import PRESETS, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer, serve_rtu_on

READ_BLOCK = struct.pack(">BHH", 4, 100, 40)


@pytest.fixture()
def responder() -> Responder:
    return Responder(RegisterBank())


def test_responder_answers_own_unit(responder):
    resp = responder.respond(reg.UNIT_ID, READ_BLOCK)
    assert resp is not None and resp[0] == 4 and resp[1] == 80
    assert responder.request_count == 1


def test_responder_ignores_other_unit(responder):
    assert responder.respond(2, READ_BLOCK) is None
    assert responder.request_count == 0


def test_responder_drop(responder):
    responder.drop_responses = True
    assert responder.respond(reg.UNIT_ID, READ_BLOCK) is None
    assert responder.request_count == 1


def test_responder_delay(responder):
    responder.delay_s = 0.05
    t0 = time.monotonic()
    assert responder.respond(reg.UNIT_ID, READ_BLOCK) is not None
    assert time.monotonic() - t0 >= 0.05


def _exchange(sock: socket.socket, tid: int, unit: int, pdu: bytes) -> bytes:
    sock.sendall(frames.build_mbap(tid, unit, pdu))
    header = sock.recv(7, socket.MSG_WAITALL)
    rtid, length, runit = frames.parse_mbap_header(header)
    assert (rtid, runit) == (tid, unit)
    return sock.recv(length - 1, socket.MSG_WAITALL)


def test_tcp_server_serves_block_and_exceptions(responder):
    with TcpSimServer(responder) as srv, socket.create_connection(srv.address, timeout=2) as sock:
        resp = _exchange(sock, 1, reg.UNIT_ID, READ_BLOCK)
        assert resp[0] == 4 and len(resp) == 82
        assert _exchange(sock, 2, reg.UNIT_ID, struct.pack(">BHH", 6, 220, 1)) == bytes([0x86, 0x01])
        assert _exchange(sock, 3, reg.UNIT_ID, struct.pack(">BHH", 4, 140, 1)) == bytes([0x84, 0x02])


def test_tcp_server_silent_for_wrong_unit_and_drop(responder):
    with TcpSimServer(responder) as srv, socket.create_connection(srv.address, timeout=0.3) as sock:
        sock.sendall(frames.build_mbap(1, 9, READ_BLOCK))
        with pytest.raises(TimeoutError):
            sock.recv(1)
        responder.drop_responses = True
        sock.sendall(frames.build_mbap(2, reg.UNIT_ID, READ_BLOCK))
        with pytest.raises(TimeoutError):
            sock.recv(1)


def test_tcp_server_stop_releases_port(responder):
    srv = TcpSimServer(responder)
    srv.start()
    addr = srv.address
    srv.stop()
    with pytest.raises(OSError):
        socket.create_connection(addr, timeout=0.3)


class FakeSerial:
    """Feeds queued chunks one byte at a time, then returns b'' (timeout)."""

    def __init__(self) -> None:
        self.rx = bytearray()
        self.tx: list[bytes] = []
        self.lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.rx += data

    def read(self, size: int = 1) -> bytes:
        with self.lock:
            if self.rx:
                out = bytes(self.rx[:size])
                del self.rx[:size]
                return out
        time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> int:
        self.tx.append(bytes(data))
        return len(data)


def _run_serial(responder: Responder, port: FakeSerial):
    stop = threading.Event()
    t = threading.Thread(target=serve_rtu_on, args=(responder, port, stop), daemon=True)
    t.start()
    return stop, t


def _wait_for(pred, timeout=2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_serial_server_answers_valid_frame(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
        unit, pdu = frames.parse_rtu(port.tx[0])
        assert unit == reg.UNIT_ID and pdu[0] == 4 and pdu[1] == 80
    finally:
        stop.set()
        t.join(2)


def test_serial_server_ignores_bad_crc_then_recovers(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        bad = bytearray(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        bad[-1] ^= 0xFF
        port.feed(bytes(bad))
        assert not _wait_for(lambda: port.tx, timeout=0.3)
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
    finally:
        stop.set()
        t.join(2)


def test_serial_server_ignores_wrong_unit(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(7, READ_BLOCK))
        assert not _wait_for(lambda: port.tx, timeout=0.3)
    finally:
        stop.set()
        t.join(2)


def test_preset_names():
    assert PRESETS == ("healthy", "critical_sensor_invalid", "stale", "frozen_sequence", "silent")


def test_preset_healthy(responder):
    apply_preset(responder, "healthy")
    s = responder.bank.published()
    assert s.module_status & reg.StatusBits.OPERATIONAL
    assert s.validity_mask & reg.CRITICAL_VALIDITY == reg.CRITICAL_VALIDITY
    assert s.fault_mask == 0 and s.critical_age_ms < reg.CRITICAL_MAX_AGE_MS
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert not responder.drop_responses


def test_preset_critical_sensor_invalid(responder):
    apply_preset(responder, "critical_sensor_invalid")
    s = responder.bank.published()
    assert not s.validity_mask & reg.ValidityBits.PERMEATE_EC
    assert s.fault_mask & reg.FaultBits.EC_PERMEATE_FAULT


def test_preset_stale(responder):
    apply_preset(responder, "stale")
    s = responder.bank.published()
    assert s.critical_age_ms == 65535
    assert s.fault_mask & reg.FaultBits.STALE_ACQUISITION


def test_preset_frozen_sequence(responder):
    apply_preset(responder, "frozen_sequence")
    before = responder.bank.published().snapshot_sequence
    responder.bank.commit()
    assert responder.bank.published().snapshot_sequence == before


def test_preset_silent(responder):
    apply_preset(responder, "silent")
    assert responder.drop_responses is True


def test_preset_unknown(responder):
    with pytest.raises(ValueError):
        apply_preset(responder, "nope")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_frames.py tests/test_server.py -q`
Expected: collection errors for missing modules.

- [ ] **Step 4: Implement `frames.py`**

```python
def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_rtu(unit: int, pdu: bytes) -> bytes:
    body = bytes([unit]) + pdu
    return body + crc16(body).to_bytes(2, "little")


def parse_rtu(frame: bytes) -> tuple[int, bytes]:
    if len(frame) < 4:
        raise FrameError(f"RTU frame too short: {len(frame)} bytes")
    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise FrameError("RTU CRC mismatch")
    return frame[0], frame[1:-2]


def build_mbap(transaction: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit) + pdu


def parse_mbap_header(header: bytes) -> tuple[int, int, int]:
    if len(header) != 7:
        raise FrameError("MBAP header must be 7 bytes")
    transaction, protocol, length, unit = struct.unpack(">HHHB", header)
    if protocol != 0 or not 2 <= length <= 254:
        raise FrameError("invalid MBAP header")
    return transaction, length, unit
```

Add docstrings.

- [ ] **Step 5: Implement `server.py`**

`Responder.respond`: if `unit != self.unit_id` return `None` without counting. Increment `request_count`. If `drop_responses`, log at debug and return `None`. If `delay_s > 0`, `time.sleep(delay_s)`. Return `self.bank.handle_pdu(pdu)`.

`TcpSimServer`: subclass-free use of `socketserver.ThreadingTCPServer` with `allow_reuse_address = True` and `daemon_threads = True`, bound in `__init__` so `address = server.server_address[:2]` is known before `start()`. Handler loop per connection: read exactly 7 header bytes (return on EOF); `parse_mbap_header` (on `FrameError` close the connection); read exactly `length - 1` PDU bytes; `resp = responder.respond(unit, pdu)`; if `resp is not None`, `sendall(build_mbap(transaction, unit, resp))`. `start()` runs `serve_forever(poll_interval=0.05)` in a daemon thread; `stop()` calls `shutdown()`, `server_close()`, joins the thread.

`serve_rtu_on(responder, port, stop)`: frame by idle gap.

```python
buf = bytearray()
while not stop.is_set():
    chunk = port.read(1)
    if chunk:
        buf += chunk
        if len(buf) > 256:
            buf.clear()
        continue
    if not buf:
        continue
    frame, buf = bytes(buf), bytearray()
    try:
        unit, pdu = parse_rtu(frame)
    except FrameError as exc:
        logger.debug("discarding frame: {}", exc)
        continue
    resp = responder.respond(unit, pdu)
    if resp is not None:
        port.write(build_rtu(unit, resp))
```

`serve_rtu(...)`: open `serial.Serial(device, baudrate=baud, bytesize=8, parity=parity, stopbits=stop_bits, timeout=0.02)` in a `with` block and call `serve_rtu_on`. The 20 ms read timeout is the idle-gap detector; it is longer than the 3.5-character RTU gap at 19200 baud and far shorter than the 1 s poll period. Import `serial` inside `serve_rtu` so tests need no port.

- [ ] **Step 6: Implement `presets.py`**

`_healthy(bank)` sets these SIMULATED values (taken from `protocol/examples/sample_snapshot.json`; they are illustrative, not equipment limits) and nothing else: `feed_ec_us_cm_x10=4257`, `permeate_ec_us_cm_x100=1830`, `permeate_flow_gpm_x1000=350`, `concentrate_flow_gpm_x1000=1050`, `ro_feed_pressure_psi_x10=1250`, `tank_volume_gal_x100=2870`, `permeate_temp_c_x100=1500`, `concentrate_temp_c_x100=1500`, `critical_age_ms=100`; `set_status(StatusBits.OPERATIONAL)`; `set_validity` of all `ValidityBits` members except `FEED_TEMP_OPTIONAL`; `set_faults(0)`.

`apply_preset(responder, name)`: reset `responder.drop_responses = False`, `responder.bank.freeze_sequence(False)`, apply `_healthy`, then:
- `healthy`: nothing more.
- `critical_sensor_invalid`: clear `ValidityBits.PERMEATE_EC` from the validity mask; `set_faults(FaultBits.EC_PERMEATE_FAULT)`.
- `stale`: `force_critical_age(65535)`; `set_faults(FaultBits.STALE_ACQUISITION)`.
- `frozen_sequence`: commit first, then `freeze_sequence(True)`.
- `silent`: `responder.drop_responses = True`.
- anything else: `raise ValueError(f"unknown preset {name!r}; choose from {PRESETS}")` before touching the bank.

Finish with `bank.commit()`.

- [ ] **Step 7: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .`

```bash
git add -A host_tools
git commit -m "Add Modbus framing, simulator transports and presets"
```

---

### Task 5: Client

**Files:**
- Create: `host_tools/src/ro_tools/client.py`
- Test: `host_tools/tests/test_client_integration.py`

**Interfaces:**
- Consumes: `Responder`, `TcpSimServer` (Task 4), `RegisterBank` (Task 3), `apply_preset` (Task 4), `ro_tools.generated.registers` (Task 2).
- Produces (`ro_tools.client`):

```python
class CommsError(Exception): ...                 # timeout, no response, cannot connect, connection lost
class ModbusExceptionError(Exception):
    code: int                                    # Modbus exception code from the server
    function_code: int

class SensorNodeClient:
    @classmethod
    def tcp(cls, host: str, port: int, *, timeout: float = 1.0, unit_id: int = UNIT_ID) -> "SensorNodeClient": ...
    @classmethod
    def serial(cls, device: str, *, baud: int = SERIAL_BAUD, parity: str = SERIAL_PARITY,
               stop_bits: int = SERIAL_STOP_BITS, timeout: float = 1.0, unit_id: int = UNIT_ID) -> "SensorNodeClient": ...
    def connect(self) -> None: ...               # CommsError if it cannot connect
    def close(self) -> None: ...
    def __enter__(self) -> "SensorNodeClient": ...   # connect()
    def __exit__(self, *exc) -> None: ...            # close()
    def read_snapshot(self) -> Snapshot: ...     # one FC04 read of INPUT_START, INPUT_COUNT
    def read_metadata(self) -> dict[str, int]: ...   # FC03 METADATA_START, METADATA_COUNT; keys from METADATA_LAYOUT
    def read_status(self) -> ControllerStatus: ...   # FC03 STATUS_START, STATUS_COUNT
    def publish_status(self, status: ControllerStatus) -> None: ...   # one FC16 of encode_status(status)
```

- [ ] **Step 1: Write failing tests**

`host_tools/tests/test_client_integration.py`:

```python
"""pymodbus client against the hand-written simulator over loopback TCP."""
import socket
import time

import pytest

from ro_tools.client import CommsError, ModbusExceptionError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.presets import apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


@pytest.fixture()
def responder() -> Responder:
    r = Responder(RegisterBank())
    apply_preset(r, "healthy")
    return r


@pytest.fixture()
def server(responder):
    with TcpSimServer(responder) as srv:
        yield srv


@pytest.fixture()
def client(server):
    with SensorNodeClient.tcp(*server.address, timeout=0.5) as c:
        yield c


def test_read_snapshot(client, responder):
    s = client.read_snapshot()
    assert s == responder.bank.published()
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert s.protocol_major == reg.PROTOCOL_MAJOR


def test_snapshot_sequence_advances_between_reads(client, responder):
    first = client.read_snapshot().snapshot_sequence
    responder.bank.commit()
    assert client.read_snapshot().snapshot_sequence == (first + 1) % 65536


def test_read_metadata(client):
    assert client.read_metadata() == {
        "configuration_schema_version": 1, "calibration_revision": 0, "device_id": 1,
    }


def test_publish_and_read_back_status(client, responder):
    status = reg.ControllerStatus(status_sequence=9, ro_state=reg.RoState.PRODUCTION,
                                  pump_commanded=reg.PumpCommanded.ON)
    client.publish_status(status)
    assert client.read_status() == status
    assert responder.bank.controller_status == status


def test_publish_invalid_status_raises_illegal_value(client, responder):
    with pytest.raises(ModbusExceptionError) as exc:
        client.publish_status(reg.ControllerStatus(ro_state=8))
    assert exc.value.code == 3 and exc.value.function_code == 16
    assert responder.bank.controller_status is None


def test_invalid_sensor_data_is_returned_faithfully(client, responder):
    apply_preset(responder, "critical_sensor_invalid")
    s = client.read_snapshot()
    assert not s.validity_mask & reg.ValidityBits.PERMEATE_EC


def test_dropped_response_raises_comms_error_without_retry(client, responder):
    client.read_snapshot()
    responder.drop_responses = True
    before = responder.request_count
    t0 = time.monotonic()
    with pytest.raises(CommsError):
        client.read_snapshot()
    assert time.monotonic() - t0 < 2.0
    assert responder.request_count == before + 1, "client must not retry silently"


def test_wrong_unit_id_gets_no_reply(server):
    with SensorNodeClient.tcp(*server.address, timeout=0.3, unit_id=9) as c:
        with pytest.raises(CommsError):
            c.read_snapshot()


def test_connect_failure_raises_comms_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(CommsError):
        SensorNodeClient.tcp("127.0.0.1", port, timeout=0.3).connect()


def test_recovers_after_drop(client, responder):
    responder.drop_responses = True
    with pytest.raises(CommsError):
        client.read_snapshot()
    responder.drop_responses = False
    assert client.read_snapshot() == responder.bank.published()


def test_server_stopped_mid_session_raises_comms_error(responder):
    srv = TcpSimServer(responder)
    srv.start()
    c = SensorNodeClient.tcp(*srv.address, timeout=0.3)
    c.connect()
    try:
        c.read_snapshot()
        srv.stop()
        with pytest.raises(CommsError):
            c.read_snapshot()
    finally:
        c.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_client_integration.py -q`
Expected: collection error, `No module named 'ro_tools.client'`.

- [ ] **Step 3: Implement `client.py`**

Wrap `pymodbus.client.ModbusTcpClient(host, port=port, timeout=timeout, retries=0)` and `pymodbus.client.ModbusSerialClient(device, baudrate=baud, bytesize=8, parity=parity, stopbits=stop_bits, timeout=timeout, retries=0)`. The private constructor takes the pymodbus client and `unit_id`.

```python
def connect(self) -> None:
    try:
        ok = self._client.connect()
    except ModbusException as exc:
        raise CommsError(str(exc)) from exc
    if not ok:
        raise CommsError("could not connect")

def _call(self, fn, *args, **kwargs):
    try:
        if not self._client.connected and not self._client.connect():
            raise CommsError("not connected")
        rr = fn(*args, device_id=self._unit_id, **kwargs)
    except (ModbusException, OSError) as exc:
        raise CommsError(str(exc)) from exc
    if rr.isError():
        raise ModbusExceptionError(rr.function_code & 0x7F, rr.exception_code)
    return rr

def read_snapshot(self) -> Snapshot:
    rr = self._call(self._client.read_input_registers, INPUT_START, count=INPUT_COUNT)
    return decode_snapshot(rr.registers)
```

`ModbusExceptionError.__init__(self, function_code: int, code: int)` stores both and formats a message. `read_metadata` builds its dict from `METADATA_LAYOUT` offsets. `publish_status` calls `self._client.write_registers(STATUS_START, encode_status(status))`.

pymodbus behaviour to confirm while making the tests pass (adjust only inside `_call`/`connect`, never the tests' intent): with `retries=0` a missing response must surface as an exception that `_call` maps to `CommsError`; if pymodbus instead returns an error object that is not an `ExceptionResponse`, detect it (`not hasattr(rr, "exception_code")` or `isinstance(rr, ModbusIOException)`) and raise `CommsError`. After a timeout pymodbus may close the connection; `_call` reconnects on the next call, which `test_recovers_after_drop` checks. If a late response to a timed-out request could be mistaken for the next reply, close and reopen the connection after any `CommsError`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass. Run the integration file three times (`uv run pytest tests/test_client_integration.py -q`) to check for flakiness; expected: identical results.

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .`

```bash
git add -A host_tools
git commit -m "Add sensor-node Modbus client with explicit error surfacing"
```

---

### Task 6: CLI and documentation

**Files:**
- Create: `host_tools/src/ro_tools/cli.py`
- Modify: `host_tools/README.md`, `CHANGELOG.md`, `protocol/README.md`
- Test: `host_tools/tests/test_cli.py`

**Interfaces:**
- Consumes: `schema.load`, `schema.SchemaError`, `schema.DEFAULT_MAP_PATH` (Task 1); `codegen.write`, `codegen.is_current` (Task 2); `RegisterBank` (Task 3); `Responder`, `TcpSimServer`, `serve_rtu`, `PRESETS`, `apply_preset` (Task 4); `SensorNodeClient`, `CommsError`, `ModbusExceptionError` (Task 5); `ro_tools.generated.registers`.
- Produces (`ro_tools.cli`):

```python
def main(argv: Sequence[str] | None = None) -> int: ...   # exit status; pyproject script entry point
def build_parser() -> argparse.ArgumentParser: ...
```

Commands and exit codes:

| Command | Behaviour | Exit |
|---|---|---|
| `validate [PATH]` | load the map (default `DEFAULT_MAP_PATH`); print `OK: protocol 1.1, 40 input words` or one violation per line to stderr | 0 / 1 |
| `generate [--check]` | write `generated/registers.py`; with `--check` write nothing and report drift | 0 / 1 on drift |
| `sim (--tcp HOST:PORT \| --serial DEVICE) [--preset NAME] [--period SECONDS]` | run the simulator, committing a new snapshot every `--period` (default 1.0) so the sequence advances; first output line contains `SIMULATED VALUES ONLY`; runs until Ctrl-C | 0 |
| `read (--tcp HOST:PORT \| --serial DEVICE) [--timeout S]` | print one decoded snapshot | 0 / 2 comms / 3 Modbus exception |
| `publish-status (--tcp HOST:PORT \| --serial DEVICE) --state NAME [--pump off\|on\|unknown] [--fault-code N] [--severity NAME] [--fault-count N] [--sequence N] [--timeout S]` | write one status block | 0 / 2 / 3 |

`--tcp` and `--serial` are a required mutually exclusive group. `--state` choices are the lower-cased `RoState` member names; `--severity` the lower-cased `FaultSeverity` names (default `none`); `--pump` default `unknown`; `--fault-code`, `--fault-count`, `--sequence` default 0.

`read` output format, one line per field, in `SNAPSHOT_LAYOUT` order:

```
protocol_major            1
feed_ec_us_cm_x10         4257   (425.7 uS/cm)
...
validity: FEED_EC|PERMEATE_EC|...
critical validity bits all set: yes
```

The last two lines print the `ValidityBits` member names set in `validity_mask`, and `yes`/`no` for whether `validity_mask & CRITICAL_VALIDITY == CRITICAL_VALIDITY`. This is a display of register contents only; the CLI makes no accept/reject decision. The unit shown in parentheses comes from the schema model (`Register.unit`), loaded via `schema.load()`.

- [ ] **Step 1: Write failing tests**

`host_tools/tests/test_cli.py`:

```python
"""CLI tests. The long-running `sim` command is covered by parser tests only."""
import pytest
import yaml

from ro_tools import cli, schema
from ro_tools.generated import registers as reg
from ro_tools.sim.presets import apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


@pytest.fixture()
def server():
    responder = Responder(RegisterBank())
    apply_preset(responder, "healthy")
    with TcpSimServer(responder) as srv:
        srv.responder = responder
        yield srv


def _tcp(server) -> str:
    return f"{server.address[0]}:{server.address[1]}"


def test_validate_ok(capsys):
    assert cli.main(["validate"]) == 0
    assert "OK: protocol 1.1, 40 input words" in capsys.readouterr().out


def test_validate_reports_violations(tmp_path, capsys):
    raw = yaml.safe_load(schema.DEFAULT_MAP_PATH.read_text(encoding="utf-8"))
    raw["input_registers"][3]["type"] = "u8"
    raw["fault_codes"][1]["source"] = "lcd"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert cli.main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "module_status" in err and "lcd" in err


def test_validate_missing_file(tmp_path):
    assert cli.main(["validate", str(tmp_path / "absent.yaml")]) == 1


def test_generate_check_is_clean():
    assert cli.main(["generate", "--check"]) == 0


def test_read_prints_decoded_snapshot(server, capsys):
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "feed_ec_us_cm_x10" in out and "(425.7 uS/cm)" in out
    assert "critical validity bits all set: yes" in out
    assert "PERMEATE_EC" in out


def test_read_shows_missing_critical_validity(server, capsys):
    apply_preset(server.responder, "critical_sensor_invalid")
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.5"]) == 0
    assert "critical validity bits all set: no" in capsys.readouterr().out


def test_read_comms_failure_exit_2(server, capsys):
    server.responder.drop_responses = True
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.3"]) == 2


def test_publish_status(server):
    rc = cli.main(["publish-status", "--tcp", _tcp(server), "--state", "production",
                   "--pump", "on", "--sequence", "4", "--timeout", "0.5"])
    assert rc == 0
    st = server.responder.bank.controller_status
    assert (st.ro_state, st.pump_commanded, st.status_sequence) == (reg.RoState.PRODUCTION, reg.PumpCommanded.ON, 4)


def test_publish_status_with_fault(server):
    rc = cli.main(["publish-status", "--tcp", _tcp(server), "--state", "fault", "--fault-code", "1001",
                   "--severity", "critical", "--fault-count", "1", "--timeout", "0.5"])
    assert rc == 0
    assert server.responder.bank.controller_status.controller_fault_code == 1001


def test_publish_inconsistent_status_exit_3(server):
    rc = cli.main(["publish-status", "--tcp", _tcp(server), "--state", "fault",
                   "--fault-code", "1001", "--timeout", "0.5"])
    assert rc == 3
    assert server.responder.bank.controller_status is None


def test_parser_sim_options():
    args = cli.build_parser().parse_args(["sim", "--tcp", "127.0.0.1:5020", "--preset", "stale"])
    assert args.preset == "stale" and args.tcp == "127.0.0.1:5020" and args.period == 1.0


@pytest.mark.parametrize(
    "argv",
    [["sim"], ["sim", "--tcp", "a:1", "--serial", "COM5"], ["sim", "--tcp", "a:1", "--preset", "nope"],
     ["read"], ["publish-status", "--tcp", "a:1"], ["publish-status", "--tcp", "a:1", "--state", "bogus"], []],
)
def test_parser_rejects(argv):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_bad_tcp_endpoint_is_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["read", "--tcp", "no-port"])
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_cli.py -q`
Expected: collection error, `cannot import name 'cli'`.

- [ ] **Step 3: Implement `cli.py`**

`build_parser()` uses `argparse` with required subcommands (`dest="command", required=True`). A helper `_endpoint(parser)` adds the required mutually exclusive `--tcp`/`--serial` group. `main` parses, configures Loguru to stderr at INFO, and dispatches to `_cmd_validate`, `_cmd_generate`, `_cmd_sim`, `_cmd_read`, `_cmd_publish_status`, each returning an int. `_parse_tcp("host:port")` splits on the last `:` and calls `parser.error(...)` (which raises `SystemExit`) when there is no port or it is not an integer.

- `_cmd_validate`: catch `schema.SchemaError` (print each violation to stderr), `OSError` and `yaml.YAMLError` (print the message to stderr); return 1 for any of them.
- `_cmd_read` / `_cmd_publish_status`: catch `CommsError` → print to stderr, return 2; `ModbusExceptionError` → print to stderr, return 3.
- `_cmd_sim`: build `Responder(RegisterBank())`, `apply_preset`, print `SIMULATED VALUES ONLY - not equipment limits; preset=<name>`. For `--tcp` start `TcpSimServer(responder, host, port)` and loop `time.sleep(period); responder.bank.commit()` until `KeyboardInterrupt`, then stop the server. For `--serial` run `serve_rtu` in a daemon thread with a `threading.Event`, run the same commit loop, and set the event on `KeyboardInterrupt`. With preset `frozen_sequence` the commits still run; the bank keeps the sequence frozen.

- [ ] **Step 4: Run tests**

Run: `uv run pytest -q`
Expected: all pass.

Run: `uv run ro-tools validate`
Expected: `OK: protocol 1.1, 40 input words`

Run: `uv run ro-tools generate --check`
Expected: exit 0.

- [ ] **Step 5: Manual end-to-end smoke**

In one terminal (or as a background process): `uv run ro-tools sim --tcp 127.0.0.1:5020 --preset healthy`
In another: `uv run ro-tools read --tcp 127.0.0.1:5020` then, a few seconds later, the same command again.
Expected: both print a snapshot; `snapshot_sequence` is larger on the second read; `critical validity bits all set: yes`. Stop the simulator.

- [ ] **Step 6: Documentation**

Replace `host_tools/README.md` with a description of the package: purpose, `uv sync`, `uv run pytest`, the five CLI commands with one example each, the rule that `generated/registers.py` is never hand-edited and is regenerated with `uv run ro-tools generate` after any change to `protocol/register_map.yaml`, a note that the simulator's values are simulated and are not equipment limits, and that snapshot acceptance, freshness expiry and fault prioritisation are deliberately not implemented here.

In `protocol/README.md` append: `Enums, controller-flag bits and the fault-code catalog are machine-readable in register_map.yaml; host_tools tests fail if the markdown tables drift from it.`

Append to `CHANGELOG.md`:

```markdown
## Stage A protocol tooling — 2026-11-11
- Added `ro_tools` host package: register-map validator, Python codec generator, simulated Modbus sensor node (TCP and serial RTU) with fault injection, pymodbus-based client, and `ro-tools` CLI.
- Added machine-readable enums, controller-flag bits, and fault codes to `protocol/register_map.yaml` (additive; protocol remains 1.1, no address/scale/signedness/access change).
- FC03 read-back of status registers 220–227 is permitted; status writes with inconsistent fault code/severity/count are rejected.
- Corrected `protocol/examples/sample_snapshot.json` protocol version to 1.1.
```

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check .` then `uv run ruff format .` then `uv run pytest -q` (all pass).

```bash
git add -A host_tools protocol CHANGELOG.md
git commit -m "Add ro-tools CLI and Stage A documentation"
```
