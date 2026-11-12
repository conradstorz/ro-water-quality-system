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
| Server implementation | Hand-written Modbus responder and framing; pymodbus is used only by the client. pymodbus 3.16's server datastore API is deprecated pending v4 and cannot express the required exception codes, silent drops, or wrong-unit silence. The pymodbus client therefore cross-checks the server as an independent implementation. |
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
      register_bank.py     pure state and PDU handling, no I/O
      frames.py            RTU CRC/framing and MBAP framing
      server.py            responder plus TCP and serial RTU transports
      presets.py           named simulator scenarios
    client.py              read/decode, publish status
    cli.py                 command-line entry point
  tests/
```

Each unit has one job and a narrow interface:

- **`schema`** depends only on PyYAML. Input: a path. Output: a `RegisterMap` model or a `SchemaError` listing every violation found.
- **`codegen`** depends only on the model. Input: `RegisterMap`. Output: source text. Deterministic: same model, byte-identical output.
- **`generated.registers`** depends on the standard library only. No YAML is read at runtime.
- **`sim.register_bank`** depends on `generated.registers` and an injected monotonic clock. It maps a request PDU to a response PDU. No sockets, no threads of its own.
- **`sim.frames`** is pure byte framing: Modbus CRC-16, RTU frames, MBAP headers.
- **`sim.server`** carries PDUs between a transport and the bank. Nothing under `sim/` imports pymodbus.
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
- **`ControllerStatus`:** frozen, keyword-only dataclass with one raw-integer field per register 220–227 and **no defaults**: every field must be given explicitly, so a forgotten `pump_commanded` is a `TypeError` and not a silent "off". (`Snapshot` keeps zero defaults; a zero snapshot has validity 0 and asserts nothing.) The constant `STATUS_REQUIRE_SEQUENCE_PROGRESS` is emitted from `controller_status_extension.require_sequence_progress`; the schema validator also checks that extension's write function code (16), write mode (`atomic_full_block_only`), `display_only` flag and `status_schema_major` against the register map.
- **`encode_snapshot(s) -> list[int]`** and **`decode_snapshot(words) -> Snapshot`** for exactly `INPUT_COUNT` words. Encoding range-checks every field against its type and raises `ValueError` on overflow; it never wraps or clamps. Reserved registers encode as zero and are ignored on decode. 32-bit values are high word first; signed values are two's complement.
- **`encode_status(s) -> list[int]`** and **`decode_status(words) -> ControllerStatus`** for exactly `STATUS_COUNT` words.
- **`validate_status(words) -> None`** raising `StatusValidationError` with a reason when: length is wrong, schema major is not 1, an enum field is out of range, a reserved flag bit is set, or the cross-field rule in section 2 is violated. An unknown non-zero `controller_fault_code` is valid, because the LCD spec requires displaying `CTRL FAULT <code>`.

Decoding performs no validity, freshness, or plausibility judgement. A decoded `Snapshot` is a faithful view of the wire, including invalid channels.

## 8. Simulated server

### 8.1 Register bank

`RegisterBank(clock)` holds:

- a **pending** snapshot that setters mutate, and a **published** snapshot that reads copy. `commit()` copies pending to published and advances `snapshot_sequence` modulo 65536. A read never observes a half-updated snapshot.
- holding metadata 200–202.
- the last accepted `ControllerStatus`, `last_valid_status_received_ms` (every valid write) and `last_status_sequence_progress_ms` (the first valid write after construction or `reboot()`, and afterwards only a valid write whose `status_sequence` differs from the previously accepted one), all taken from the injected clock. A publisher that keeps rewriting an unchanged block therefore cannot look fresh to a consumer that checks sequence progress. The bank stores the timestamps; it applies no expiry.
- `last_rejection`: a short reason (including the `StatusValidationError` text for FC16 value rejections) for the most recent `handle_pdu` call that returned an exception response; reset to `None` by a call that returned a normal response. The bank stays pure: it does no logging.

Operations and their results:

| Request | Result |
|---|---|
| FC04, range inside 100–139 | words from the published snapshot |
| FC04, any address outside 100–139 | exception 0x02 illegal data address |
| FC03, range inside 200–202 or inside 220–227 | stored values |
| FC03, any other address, or a range spanning the 203–219 gap | exception 0x02 |
| FC16, exactly 220–227 (8 words), passes `validate_status` | accepted; status and timestamps updated |
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
- `reboot()`: increments `boot_counter` (saturating at the u32 maximum, never wrapping, and setting status bit `overflow_or_saturation` when it is already there), zeroes `uptime_seconds`, resets the sequence to 0, sets status bit `watchdog_reset_seen`, discards the stored controller status and both status timestamps, and commits immediately

Methods on the server adapter, effective immediately:

- `drop_responses(on)`: requests are received and no reply is sent
- `delay_responses(ms)`

A default bank starts with simulated values clearly labelled as simulated in logs and CLI output. They are illustrative and are not equipment limits.

### 8.3 Adapter

`sim.server` exposes a `Responder` (bank, unit ID, drop and delay controls), a `TcpSimServer` running in a background thread, and `open_serial_port(device, ...)`, which opens a serial port (8 data bits, 20 ms read timeout) with defaults from the generated constants for `serve_rtu_on`; the CLI uses it instead of building its own port. Both transports use the same responder. A unit ID other than `UNIT_ID` receives no reply. A request whose function code has the `0x80` bit set also receives no reply (on a 2-wire serial adapter the simulator can hear its own exception response echoed back and must not answer it). Whenever the response is an exception, `Responder.respond` logs at WARNING the request function code, the exception code and `bank.last_rejection`. The serial transport delimits frames by idle gap and silently discards frames with a bad CRC.

## 9. Client

`SensorNodeClient` is constructed over TCP or serial RTU and provides:

- `read_snapshot() -> Snapshot`: one FC04 read of the full block, then `decode_snapshot`.
- `read_metadata()`: FC03 200–202.
- `read_status() -> ControllerStatus | None`: FC03 220–227. All-zero words mean the node has received no valid status since boot and return `None`, never a zero-valued status. Otherwise the words are run through `validate_status`; a failure raises `ProtocolError`.
- `publish_status(status)`: one FC16 write of the full block.

Transport failures raise `CommsError` (timeout, no response, connection lost). A Modbus exception response raises `ModbusExceptionError` carrying the exception code and the function code of the request that was sent. pymodbus does not check that a reply matches its request, so the client does: the reply's function code must equal the request's, a read must return exactly the requested register count, the FC16 echo must carry `STATUS_START` and `STATUS_COUNT`, and an exception reply must carry the request's function code with bit `0x80`. Any mismatch raises `ProtocolError` (a `CommsError` subclass), and the connection is closed as for any transport failure. No malformed reply leaks a bare `ValueError` or `IndexError`. The client never retries silently and never returns a cached or default snapshot.

## 10. CLI

`uv run ro-tools <command>`:

| Command | Purpose |
|---|---|
| `validate [PATH]` | Validate the register map; non-zero exit and a list of violations on failure |
| `generate [--check]` | Write `generated/registers.py`; `--check` exits non-zero on drift without writing |
| `sim --tcp HOST:PORT` or `--serial PORT` `[--preset NAME]` | Run the simulated sensor node |
| `read --tcp ...` or `--serial ...` | Read and print one decoded snapshot with validity bits |
| `publish-status --tcp ...` or `--serial ...` `--state ... --fault-code ...` | Write one status block |

Global option: `-v` / `--verbose` sets the Loguru level to DEBUG (default INFO). `--tcp` ports must be 0–65535 and `--timeout` must be greater than 0. `publish-status` range-checks the status (`encode_status`) before connecting; it does not run `validate_status`, so an inconsistent block is still sent and the node's own rejection (exit 3) is observable.

Presets for `sim`: `healthy`, `critical_sensor_invalid`, `stale`, `frozen_sequence`, `silent`.

## 11. Error handling

- Schema violations are collected and reported together, each naming the offending register or key.
- Codec functions raise on wrong length or out-of-range values; they never substitute a value.
- The simulator maps every rejected request to a specific Modbus exception code; `Responder` logs each one at WARNING with the reason from `bank.last_rejection`.
- The client distinguishes transport failure, a Modbus exception and a reply that does not match its request (`ProtocolError`), and surfaces all of them to the caller.

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

`pyyaml`, `pymodbus[serial]~=3.16.0` (client only; the 3.x API changes between minors), `pyserial`, `loguru`. Dev: `pytest`, `hypothesis`, `ruff`. A `[project.scripts]` entry adds `ro-tools`.

## 14. Follow-on work enabled

- Stage F fault-priority engine and status freshness, tested against this simulator.
- Main-controller polling, snapshot acceptance, and state machine on the host.
- Bench testing real sensor-node firmware with `ro-tools read --serial`, and real main-controller firmware against `ro-tools sim --serial`.
