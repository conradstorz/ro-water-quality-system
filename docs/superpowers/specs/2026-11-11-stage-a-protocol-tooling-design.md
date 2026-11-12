# Stage A — protocol tooling design

**Date:** 2026-11-11 · **Status:** approved design, pre-implementation · **Scope:** `host_tools/` and additive metadata in `protocol/register_map.yaml`

## 1. Goal

Deliver Stage A of `docs/CLAUDE_IMPLEMENTATION_BRIEF.md`: validate the normative register map, generate a typed Python codec from it, and provide a simulated Modbus server and client that later stages (fault-priority engine, main-controller logic, firmware bench tests) build on. Everything runs on the host with no hardware.

## 2. Decisions

| Topic | Decision |
|---|---|
| Codegen target | Python only. The schema model is backend-neutral so a C or MicroPython emitter can be added once the firmware runtime is chosen. |
| YAML → code | Generated source file, committed to the repo, with a test that regenerates and fails on drift. |
| Test transport | Modbus TCP on localhost (ephemeral port) for automated tests. The same server and client can run RTU over a real serial port from the CLI. |
| Enums and fault codes | Added to `register_map.yaml` as additive metadata. Protocol version stays 1.1; no address, scale, signedness, or access change. |
| Stage boundary | Protocol-complete simulator with fault injection. No acceptance policy, no freshness expiry, no fault prioritisation. |
| FC03 on 220–227 | Readable: returns the last accepted status block, zeros before the first valid write. |
| Status cross-field check | A block is rejected unless `controller_fault_code == 0`, `controller_fault_severity == 0`, and `controller_fault_count == 0` are either all true or all false. |

## 3. Out of scope

- Snapshot accept/reject rules and the 3-second production inhibit (main-controller sub-project).
- Controller-status expiry, fault merging, priority, and LCD rendering (Stage F sub-project).
- C or MicroPython emitters, firmware, calibration tooling, log analysis.
- Any writable calibration or configuration register.

## 4. Package layout

```
host_tools/
  pyproject.toml
  src/ro_tools/
    __init__.py
    schema.py              YAML -> validated frozen model
    codegen.py             model -> Python source text
    generated/
      __init__.py
      registers.py         GENERATED, committed
    sim/
      __init__.py
      register_bank.py     pure state, no I/O
      server.py            pymodbus adapter (TCP or serial RTU)
    client.py              read/decode, publish status
    cli.py                 command-line entry point
  tests/
```

Each unit has one job and a narrow interface:

- **`schema`** depends only on PyYAML. Input: a path. Output: a `RegisterMap` model or a `SchemaError` listing every violation found.
- **`codegen`** depends only on the model. Input: `RegisterMap`. Output: source text. Deterministic: same model, byte-identical output.
- **`generated.registers`** depends on the standard library only. No YAML is read at runtime.
- **`sim.register_bank`** depends on `generated.registers` and an injected monotonic clock. No sockets, no threads of its own, no pymodbus imports.
- **`sim.server`** adapts the bank to pymodbus. It contains transport and exception-code mapping only.
- **`client`** depends on pymodbus and `generated.registers`.
- **`cli`** wires the above together and configures Loguru.

## 5. Register-map additions

Additive keys in `protocol/register_map.yaml`:

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
controller_flags_bits: {}        # all bits reserved; must be written as zero
fault_codes:
  - {code: 0,    source: controller, default_severity: none,     description: No active fault}
  - {code: 1001, source: controller, default_severity: critical, description: High RO feed pressure interlock}
  # ... one entry per row of docs/specs/FAULT_CODE_CATALOG.md
  - {code: 4001, source: sensor, default_severity: critical, state_dependent: true,
     description: Critical local measurement invalid or stale}
```

Holding registers 222, 223, and 225 gain an `enum:` key naming the enum above. Register 220 gains `equals: 1`.

`protocol/examples/sample_snapshot.json` is corrected from protocol `1.0` to `1.1`.

A test parses the tables in `docs/specs/FAULT_CODE_CATALOG.md` and `protocol/CONTROLLER_STATUS_EXTENSION.md` and fails if codes, severities, RO states, or register addresses disagree with the YAML. The YAML remains normative; the markdown is checked against it.

## 6. Validator rules

`schema.load()` rejects the map when any of these fail, reporting all failures together:

1. Required top-level keys are present; `addressing` is `zero_based_pdu_offset`; `word_order_32bit` is `high_word_first`; `byte_order_per_word` is `big_endian`.
2. Every register `type` is one of `u16`, `i16`, `u32`, `i32`, and `words` equals 1 for 16-bit types and 2 for 32-bit types.
3. Within each table no two registers occupy the same address.
4. Input registers cover `polling.input_start` through `input_start + input_count - 1` contiguously, with no gap and nothing outside.
5. `scale_divisor` is a positive integer, defaulting to 1 when absent (holding registers omit it). A name ending `_x10`, `_x100`, or `_x1000` has the matching divisor; a name without such a suffix has divisor 1.
6. Register names are unique across both tables and are valid Python identifiers.
7. Bit indices in `validity_bits`, `status_bits`, `fault_bits`, and `controller_flags_bits` are 0–15 and unique per table. `critical_validity_bits` is a subset of `validity_bits`.
8. `controller_status_extension.start` and `count` match exactly the holding registers whose access is `write_multiple_only`, and those registers are contiguous.
9. `access` is one of `read_only`, `write_multiple_only`.
10. Every `enum:` reference resolves; enum values are unique non-negative integers that fit in 16 bits.
11. Fault codes are unique, fit in 16 bits, have `source` of `controller` or `sensor`, and a `default_severity` that is a member of `fault_severity`. Code 0 exists with severity `none`.

## 7. Generated module

`generated/registers.py` begins with a do-not-edit header naming the generator and the protocol version. It contains:

- **Constants:** `PROTOCOL_MAJOR`, `PROTOCOL_MINOR`, `UNIT_ID`, serial defaults, `INPUT_START`, `INPUT_COUNT`, `STATUS_START`, `STATUS_COUNT`, timeouts, and one address constant per register.
- **Flags:** `ValidityBits`, `StatusBits`, `FaultBits` as `IntFlag`; `CRITICAL_VALIDITY` as a `ValidityBits` value.
- **Enums:** `RoState`, `PumpCommanded`, `FaultSeverity` as `IntEnum`; `FAULT_CODES` as a mapping from code to a frozen record.
- **`Snapshot`:** frozen dataclass with one raw-integer field per non-reserved input register, plus read-only properties giving engineering units as `float` (for example `feed_ec_us_cm` returns `feed_ec_us_cm_x10 / 10`).
- **`ControllerStatus`:** frozen dataclass with one raw-integer field per register 220–227.
- **`encode_snapshot(s) -> list[int]`** and **`decode_snapshot(words) -> Snapshot`** for exactly `INPUT_COUNT` words. Encoding range-checks every field against its type and raises `ValueError` on overflow; it never wraps or clamps. Reserved registers encode as zero and are ignored on decode. 32-bit values are high word first; signed values are two's complement.
- **`encode_status(s) -> list[int]`** and **`decode_status(words) -> ControllerStatus`** for exactly `STATUS_COUNT` words.
- **`validate_status(words) -> None`** raising `StatusValidationError` with a reason when: length is wrong, schema major is not 1, an enum field is out of range, a reserved flag bit is set, or the cross-field rule in section 2 is violated. An unknown non-zero `controller_fault_code` is valid, because the LCD spec requires displaying `CTRL FAULT <code>`.

Decoding performs no validity, freshness, or plausibility judgement. A decoded `Snapshot` is a faithful view of the wire, including invalid channels.

## 8. Simulated server

### 8.1 Register bank

`RegisterBank(clock)` holds:

- a **pending** snapshot that setters mutate, and a **published** snapshot that reads copy. `commit()` copies pending to published and advances `snapshot_sequence` modulo 65536. A read never observes a half-updated snapshot.
- holding metadata 200–202.
- the last accepted `ControllerStatus` and `last_valid_status_received_ms` taken from the injected clock. The bank stores the timestamp; it applies no expiry.

Operations and their results:

| Request | Result |
|---|---|
| FC04, range inside 100–139 | words from the published snapshot |
| FC04, any address outside 100–139 | exception 0x02 illegal data address |
| FC03, range inside 200–202 or inside 220–227 | stored values |
| FC03, any other address, or a range spanning the 203–219 gap | exception 0x02 |
| FC16, exactly 220–227 (8 words), passes `validate_status` | accepted; status and timestamp updated |
| FC16, exactly 220–227, fails `validate_status` | exception 0x03 illegal data value; prior status and timestamp kept |
| FC16, any other start or count, including any touching 200–202 | exception 0x02; prior status kept |
| FC06 or any other function code | exception 0x01 illegal function |

### 8.2 Fault injection

Methods on the bank, each affecting the next `commit()` unless noted:

- `set_validity(bits)`, `set_faults(bits)`, `set_status(bits)`
- `set_field(name, raw)` for any snapshot field
- `freeze_sequence(on)`: `commit()` publishes without advancing the sequence
- `force_critical_age(ms)`: saturates at 65535
- `saturate(field)`: sets the field to its type maximum and sets status bit `overflow_or_saturation`
- `reboot()`: increments `boot_counter`, zeroes `uptime_seconds`, resets the sequence to 0, sets status bit `watchdog_reset_seen`, discards the stored controller status, and commits immediately

Methods on the server adapter, effective immediately:

- `drop_responses(on)`: requests are received and no reply is sent
- `delay_responses(ms)`

A default bank starts with simulated values clearly labelled as simulated in logs and CLI output. They are illustrative and are not equipment limits.

### 8.3 Adapter

`sim.server` exposes `serve_tcp(bank, host, port)` and `serve_rtu(bank, port, baud, parity, stop_bits)` with serial defaults from the generated constants. Both use the same request handling. Unit ID other than `UNIT_ID` receives no reply.

## 9. Client

`SensorNodeClient` is constructed over TCP or serial RTU and provides:

- `read_snapshot() -> Snapshot`: one FC04 read of the full block, then `decode_snapshot`.
- `read_metadata()`: FC03 200–202.
- `read_status() -> ControllerStatus`: FC03 220–227.
- `publish_status(status)`: one FC16 write of the full block.

Transport failures raise `CommsError` (timeout, no response, connection lost). A Modbus exception response raises `ModbusExceptionError` carrying the exception code. The client never retries silently and never returns a cached or default snapshot.

## 10. CLI

`uv run ro-tools <command>`:

| Command | Purpose |
|---|---|
| `validate [PATH]` | Validate the register map; non-zero exit and a list of violations on failure |
| `generate [--check]` | Write `generated/registers.py`; `--check` exits non-zero on drift without writing |
| `sim --tcp HOST:PORT` or `--serial PORT` `[--preset NAME]` | Run the simulated sensor node |
| `read --tcp ...` or `--serial ...` | Read and print one decoded snapshot with validity bits |
| `publish-status --tcp ...` or `--serial ...` `--state ... --fault-code ...` | Write one status block |

Presets for `sim`: `healthy`, `critical_sensor_invalid`, `stale`, `frozen_sequence`, `silent`.

## 11. Error handling

- Schema violations are collected and reported together, each naming the offending register or key.
- Codec functions raise on wrong length or out-of-range values; they never substitute a value.
- The simulator maps every rejected request to a specific Modbus exception code and logs the reason.
- The client distinguishes transport failure from a Modbus exception, and surfaces both to the caller.

## 12. Testing

pytest and hypothesis, run with `uv run pytest` from `host_tools/`.

- **Schema:** the real map loads; each validator rule has a negative test using a mutated copy of the map.
- **Docs consistency:** markdown tables agree with the YAML.
- **Codegen:** deterministic output; committed `registers.py` matches a fresh generation.
- **Codec:** hypothesis round-trip `decode(encode(s)) == s` over the full range of every field; explicit cases for i16 and i32 at minimum, -1, 0, and maximum; u32 word order checked against hand-written word pairs; overflow raises; wrong length raises; reserved words ignored on decode.
- **Wire format:** an RTU request for the input block encodes start address 100 as bytes `00 64` and count 40 as `00 28`, with a correct CRC16; a frame with a corrupted CRC is rejected by the framer.
- **Register bank:** the full table in section 8.1; status preserved after each rejected write; unknown fault code accepted; sequence rollover 65535 → 0; reboot discontinuity; frozen sequence; a reader thread never sees a snapshot mixing two commits while a writer thread commits continuously.
- **Integration over loopback TCP:** read snapshot, read metadata, publish and read back status, each exception path, dropped responses raise `CommsError` within the client timeout, wrong unit ID gets no reply.

## 13. Dependencies

`pyyaml`, `pymodbus` pinned to a single minor series (the 3.x API changes between minors; the exact series is chosen and verified at implementation time), `loguru`. Dev: `pytest`, `hypothesis`, `ruff`. A `[project.scripts]` entry adds `ro-tools`.

## 14. Follow-on work enabled

- Stage F fault-priority engine and status freshness, tested against this simulator.
- Main-controller polling, snapshot acceptance, and state machine on the host.
- Bench testing real sensor-node firmware with `ro-tools read --serial`, and real main-controller firmware against `ro-tools sim --serial`.
