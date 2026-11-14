# 1-Wire Input Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Add a monitoring-only 1-Wire input (up to 8 mixed-family devices) to the protocol, host simulator, host monitor and hardware docs.

**Architecture:** Protocol 1.2 -> 1.3, additive. The input polling window grows from 100-139 to 100-199; 140-199 holds a 4-word header and 8 slots of 7 words. Slot fields are ordinary generated snapshot fields, so `RegisterBank.set_field` works unchanged. A new `ro_tools/onewire.py` owns ROM-ID/slot decode and the simulated device model. `monitor.py` gains a separate `evaluate_onewire` that never touches `production_permitted`.

**Tech Stack:** Python 3.12 via `uv`, pytest, ruff, existing `ro-tools generate` codegen. Spec: `docs/superpowers/specs/2026-11-13-onewire-input-design.md`. Run host tests from `host_tools/` with `uv run pytest`.

## Global Constraints

- AGENTS.md rule 2: no existing register address, scale, signedness or write permission changes. Only additions plus the version bump 1.2 -> 1.3 and `polling.input_count` 40 -> 100.
- AGENTS.md rule 5: never guess pinouts, voltages, GPIO, pull-ups, cable length, connector ratings. Keep every TBD from spec section 8 visible as TBD.
- 1-Wire bits are NEVER added to `validity_bits`/`critical_validity_bits`, and `production_permitted` results must be identical with and without 1-Wire faults.
- No value is ever substituted by a plausible default; an unsupported family reports ROM ID only with zero value words and `valid` clear.
- Register layout (exact): 140 `onewire_device_count` u16; 141 `onewire_bus_status` u16 (bit0 bus_short, 1 no_presence, 2 crc_errors, 3 overflow); 142 `onewire_scan_generation` u16; 143 `onewire_age_ms` u16 (saturates 65535); slot n (0..7) base = 144 + 7n: `onewire_sN_rom0..rom3` u16 (64-bit ROM, big-endian, high word first, family code = low byte of rom3), `onewire_sN_primary` i16, `onewire_sN_secondary` i16, `onewire_sN_status` u16. Slot status bits: 0 present, 1 valid, 2 stale, 3 crc_error, 4 unsupported_family, 5 missing. Fault bit 10 `onewire_bus_fault`.
- Families: 0x28 DS18B20 primary = degC x100; 0x26 DS2438 primary = degC x100, secondary = mV; any other = unsupported.
- Slots sorted by ROM ID ascending; more than 8 devices -> report the 8 lowest, set `bus_status` bit 3.
- Python style per AGENTS.md: type annotations, Sphinx docstrings, pathlib, Loguru for host tools. Commits end with `Assisted-by: <model actually writing it> (Claude Code)`; do not chain shell commands with `&&`.

---

### Task 1: Protocol 1.3 register map and generated codec

**Files:**
- Modify: `protocol/register_map.yaml`, `host_tools/src/ro_tools/generated/registers.py` (via `uv run ro-tools generate`), `protocol/*` docs that list the version or window (grep for `1.2` and `input_count`/`40`), `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`, `protocol/REGISTER_MAP_REFERENCE.md` (if present), `CHANGELOG.md`
- Create: `host_tools/tests/test_protocol_v13.py`
- Modify tests that hard-code version 1.2 or 40 words (`test_register_map.py`, `test_codec.py`, `test_register_bank.py`, `test_protocol_v12.py`, `test_docs_consistency.py`, etc.): update to 1.3 / 100 words where they assert the window; keep their address assertions.

**Interfaces:**
- Produces: generated `Snapshot` fields named exactly as in Global Constraints; `FaultBits.ONEWIRE_BUS_FAULT` (bit 10); `INPUT_COUNT == 100`; `PROTOCOL_MINOR == 3`.

- [ ] **Step 1: Write failing `test_protocol_v13.py`.** Tests: (a) minor == 3, `INPUT_COUNT == 100`, `INPUT_START == 100`; (b) every v1.2 register name still has its v1.2 address, type and scale (hard-code the 100-139 table from the pre-change YAML via `git show HEAD:protocol/register_map.yaml` parse is NOT allowed; hard-code a literal dict of at least addresses 100,109,113,117,125,132,133,134); (c) addresses 140-143 and slot fields land at 144+7n+offset for all 8 slots (loop); (d) `onewire_sN_primary/secondary` are `i16`, all others `u16`; (e) 135-139 still reserved; (f) `FaultBits.ONEWIRE_BUS_FAULT == 1 << 10`; (g) `critical_validity_bits` unchanged and `ValidityBits` has no 1-Wire member (still 11 bits 0..10); (h) encode/decode round-trip of a Snapshot with non-zero slot fields.
- [ ] **Step 2: Run, confirm FAIL.** `uv run pytest tests/test_protocol_v13.py -q` from `host_tools/`.
- [ ] **Step 3: Edit `protocol/register_map.yaml`.** Bump `version.minor` to 3, `polling.input_count` to 100, add fault bit `10: onewire_bus_fault`, add input registers 140-199 per Global Constraints (generate the 60 YAML entries with a throwaway script in the scratchpad dir, not committed; each with `words: 1`, `scale_divisor: 1`, `access: read_only`, units `count`/`bitmask`/`ms`/`raw`/`degC_x100`-style text matching existing unit conventions). Use `uv run ro-tools validate` to check schema.
- [ ] **Step 4: Regenerate.** `uv run ro-tools generate` then `uv run ro-tools generate --check` (must be current).
- [ ] **Step 5: Fix affected existing tests and docs** (version/window assertions, docs-consistency, changelog entry "Protocol 1.3: 1-Wire block 140-199, additive"). Update the Modbus spec polling text and register reference for the new window and registers.
- [ ] **Step 6: Run full suite** `uv run pytest -q` and `uv run ruff check .` — all green. Commit `feat(protocol): 1.3 1-Wire register block 140-199`.

### Task 2: `ro_tools/onewire.py` — ROM/slot model and simulated devices

**Files:**
- Create: `host_tools/src/ro_tools/onewire.py`, `host_tools/tests/test_onewire.py`
- Modify: `host_tools/src/ro_tools/sim/register_bank.py` (add `set_onewire`)

**Interfaces:**
- Produces in `onewire.py`:
  - `SLOT_COUNT = 8`; `class SlotStatus(IntFlag)`: `PRESENT=1, VALID=2, STALE=4, CRC_ERROR=8, UNSUPPORTED_FAMILY=16, MISSING=32`; `class BusStatus(IntFlag)`: `BUS_SHORT=1, NO_PRESENCE=2, CRC_ERRORS=4, OVERFLOW=8`.
  - `FAMILY_DS18B20 = 0x28`, `FAMILY_DS2438 = 0x26`.
  - `dallas_crc8(data: bytes) -> int` (Maxim/Dallas CRC-8, poly 0x8C reflected).
  - `make_rom(family: int, serial: int) -> int` builds a 64-bit ROM: byte0 family, bytes1-6 serial (48-bit), byte7 CRC8 of first 7 bytes. Convention in registers: the 64-bit integer is `rom`, rom0 = bits 63..48 ... rom3 = bits 15..0, so family code (low byte of the ID per spec) = `rom & 0xFF` when ROM ID is read little-endian per Dallas wire order. To avoid ambiguity: define `rom_family(rom) -> int` as `rom & 0xFF` and `make_rom` places family in the LOW byte, serial in bytes 1-6 above it, CRC in the HIGH byte (bits 63..56). `rom_crc_ok(rom) -> bool` recomputes CRC8 over the low 7 bytes in little-endian order (low byte first).
  - `@dataclass(frozen=True) class OneWireDevice`: `rom: int`, `primary: int = 0`, `secondary: int = 0`, `present: bool = True`, `valid: bool = True`, `stale: bool = False`, `crc_error: bool = False`, `missing: bool = False`.
  - `@dataclass(frozen=True) class SlotReading`: `rom: int`, `primary: int`, `secondary: int`, `status: SlotStatus`; property `usable -> bool` true only when VALID set and STALE, CRC_ERROR, MISSING, UNSUPPORTED_FAMILY clear.
  - `slot_words(device: OneWireDevice) -> dict[str, int]` helper is internal; public `encode_onewire(devices: Sequence[OneWireDevice], bus_status: BusStatus = BusStatus(0), age_ms: int = 0, generation: int = 0) -> dict[str, int]` returning snapshot-field-name -> raw value for fields 140-199: sorts by ROM ascending, truncates to 8 and sets OVERFLOW if more, clears VALID/zeros values for unsupported families (setting UNSUPPORTED_FAMILY, PRESENT), computes status bits from the device flags (a `missing` device: PRESENT clear, MISSING set, VALID clear), `device_count` = count of PRESENT slots, `age_ms` saturates at 65535, unused slots all zero. A device flagged `crc_error` has VALID cleared and values zeroed.
  - `decode_slots(snapshot: Snapshot) -> tuple[SlotReading, ...]` returning only non-empty slots (any non-zero word), in slot order; `rom` reassembled from rom0..rom3 high word first. Uses `getattr` on the snapshot fields.
- Produces in `RegisterBank`: `set_onewire(devices, bus_status=BusStatus(0), age_ms=0, generation=0) -> None` which calls `encode_onewire` and `set_field` for every returned name atomically (hold the lock once; reuse range checks).
- Consumes: Task 1 generated `Snapshot` fields.

- [ ] **Step 1: Write failing `test_onewire.py`** covering: `dallas_crc8` known vector (`bytes.fromhex("0200000000000000")[:7]`-style: use the Maxim app-note vector `dallas_crc8(bytes([0x02,0x1C,0xB8,0x01,0x00,0x00,0x00])) == 0xA2`); `make_rom`/`rom_crc_ok`/`rom_family` round trip and a flipped bit fails CRC; encode+decode round trip for one DS18B20 (primary 2150) and one DS2438 (primary 2210, secondary 3300) giving usable readings; slots sorted by ROM ascending regardless of input order; 9 devices -> 8 slots, OVERFLOW set, the 8 lowest ROMs kept; unsupported family (0x01) -> UNSUPPORTED_FAMILY, VALID clear, value words zero, ROM present; `crc_error` device -> unusable, values zero; `missing` device keeps its slot with MISSING set and PRESENT clear, and is not counted in `device_count`; `age_ms=70000` saturates to 65535; empty input -> all 60 fields zero; duplicate ROM raises `ValueError` (a bus cannot hold two identical ROMs); `RegisterBank.set_onewire` then `commit` then `encode_snapshot`/`decode_slots` round trip via the bank's published snapshot (use the bank's existing public accessor for the published snapshot; if none, assert via a Modbus FC4 read of 100..199 through `handle_pdu`).
- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement `onewire.py` and `RegisterBank.set_onewire`.**
- [ ] **Step 4: Run `uv run pytest tests/test_onewire.py tests/test_register_bank.py -q`, ruff, then full suite.** Commit `feat(sim): 1-Wire slot model and register bank support`.

### Task 3: Presets, simulator CLI and `read` table

**Files:**
- Modify: `host_tools/src/ro_tools/sim/presets.py`, `host_tools/src/ro_tools/cli.py`
- Create: `host_tools/tests/test_onewire_presets_cli.py`

**Interfaces:**
- Consumes: `onewire.encode_onewire`, `OneWireDevice`, `BusStatus`, `decode_slots`, `RegisterBank.set_onewire`.
- Produces: new presets appended to `PRESETS`: `onewire_healthy` (one DS18B20 primary 2150 + one DS2438 primary 2210 secondary 3300, SIMULATED), `onewire_lost` (same devices, the DS18B20 `missing`, `BusStatus.NO_PRESENCE` not set, fault bit 10 raised), `onewire_crc_error` (DS18B20 crc_error, `BusStatus.CRC_ERRORS`, fault bit 10 raised), `onewire_overflow` (9 DS18B20 devices, `BusStatus.OVERFLOW`, fault bit 10 raised). All apply on top of the node's healthy snapshot (`_healthy`) so every validity/critical bit stays exactly as in `healthy`. Existing presets leave the 1-Wire block all zero. CLI `read` prints, when `decode_slots` is non-empty or bus_status non-zero, a table: slot, ROM (16 hex digits), family name (DS18B20/DS2438/unsupported 0xNN), primary, secondary, status flags; it prints `usable` only when `SlotReading.usable`. `read` never changes its exit code because of 1-Wire state.

- [ ] **Step 1: Write failing tests:** each new preset name is in `PRESETS`; applying `onewire_healthy` leaves `validity_mask` equal to the profile's healthy validity and fault_mask without bit 10; `onewire_lost`/`crc_error`/`overflow` set fault bit 10 and leave `validity_mask` identical to healthy; `pressure_failed` and the other old presets keep the 1-Wire block zero; CLI `read` against a simulated server with `onewire_healthy` prints both ROM IDs and `usable`, and with `onewire_lost` prints `missing` and exit code equals the healthy exit code (reuse the helper pattern from `test_cli_multinode.py`).
- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement.** Keep `apply_preset` signature unchanged. Update the `sim` CLI help/choices if they enumerate presets from `PRESETS` (verify; no hand-copied list may go stale).
- [ ] **Step 4: Run the new tests, `test_cli*.py`, `test_presets_profiles.py`, ruff, full suite.** Commit `feat(sim): 1-Wire presets and read table`.

### Task 4: Monitor — `evaluate_onewire`, monitoring only

**Files:**
- Modify: `host_tools/src/ro_tools/monitor.py`
- Create: `host_tools/tests/test_monitor_onewire.py`

**Interfaces:**
- Consumes: `onewire.decode_slots`, `SlotReading`, `BusStatus`, `SlotStatus`; the existing `Snapshot`/`NodeHealth`/`production_permitted` in `monitor.py` (read them first; do not change their signatures or behaviour).
- Produces: `class OneWireState(Enum)`: `OK`, `DEGRADED`, `UNAVAILABLE`; `@dataclass(frozen=True) class OneWireBinding`: `role: str`, `rom: int`; `@dataclass(frozen=True) class OneWireHealth`: `state: OneWireState`, `values: Mapping[str, SlotReading]` (role -> reading, only usable ones), `missing_roles: tuple[str, ...]`, `unbound_roms: tuple[int, ...]`, `reasons: tuple[str, ...]`; `evaluate_onewire(snapshot: Snapshot, bindings: Sequence[OneWireBinding]) -> OneWireHealth`.
- Rules: a bound role whose ROM has no slot, or whose slot is not `usable`, goes in `missing_roles` (state DEGRADED, reason names the role and cause); bus_status bits or fault bit 10 set -> DEGRADED at least; bus_short or no_presence with bound roles -> UNAVAILABLE; ROMs present but not bound -> `unbound_roms` (informational, state unaffected); no bindings and no devices -> OK; duplicate `role` or duplicate `rom` in bindings raises `ValueError`. Never returns a default value for an unusable role.

- [ ] **Step 1: Write failing tests** for each rule above, plus the invariance test: for a fixed healthy `NodeHealth`/`NodeConfig` setup used by the existing `test_monitor.py` (copy its fixtures), `production_permitted(...)` returns the same result for snapshots built with healthy 1-Wire, lost, crc-error, overflow and all-garbage 1-Wire words; and a source check that `monitor.production_permitted`/`evaluate` do not reference `onewire` (assert on `inspect.getsource`).
- [ ] **Step 2: Run, confirm FAIL.**
- [ ] **Step 3: Implement.** `evaluate_onewire` must not be called from `evaluate` or `production_permitted`.
- [ ] **Step 4: Run `tests/test_monitor.py tests/test_monitor_onewire.py`, ruff, full suite.** Commit `feat(monitor): 1-Wire health, monitoring only`.

### Task 5: Hardware docs, ADR-0009 and consistency tests

**Files:**
- Modify: `hardware/interconnect/pinout.yaml`, `hardware/interconnect/NODE_BUS_INTERCONNECT.md`, `hardware/sensor-node/HARDWARE_SPEC.md`, `docs/test/ACCEPTANCE_TEST_PLAN.md` (add 1-Wire cases), `docs/superpowers/specs/2026-11-13-onewire-input-design.md` only if the tasks above forced a deviation, `CHANGELOG.md`, `host_tools/tests/test_interconnect_docs.py`
- Create: `docs/decisions/ADR-0009-onewire-monitoring-input.md`

**Interfaces:** none (docs). Consumes the Global Constraints and spec sections 2, 4, 8.

- [ ] **Step 1: Extend `test_interconnect_docs.py` first** (read it, follow its style): `pinout.yaml` has a `onewire` section naming connector "Nilight 3-pin waterproof male/female harness connector" with signals +5V, DATA, GND whose `cavity` values are the literal string `TBD`; the same doc/YAML states `rating_voltage: TBD` and `rating_current: TBD`; `NODE_BUS_INTERCONNECT.md` contains "1-WIRE" label guidance and says the connector is not for the RJ45 RO BUS; ADR-0009 exists with status Proposed and states monitoring-only; no file under `hardware/` assigns a GPIO or pull-up value to the 1-Wire bus (grep for the words and require TBD). Run, confirm FAIL.
- [ ] **Step 2: Write the docs.** `pinout.yaml` `onewire:` section (connector, signals with cavity TBD, power from node 5 V rail non-parasitic, polyfuse TBD, pull-up TBD, GPIO TBD, max length TBD, shield bonded node end only, one male-end + one female-end pigtail per node). `NODE_BUS_INTERCONNECT.md` new "1-Wire bus" section: pigtail through cable gland, daisy-chain at plug/socket pairs, label "1-WIRE", keep away from 24 V and RS485 wiring, generic 3-pin automotive plugs mate with each other (hazard), monitoring only. `HARDWARE_SPEC.md`: 1-Wire front end block with TBDs. ADR-0009 (Proposed): decision monitoring-only, ROM-ID binding in controller config, window 100-199, alternatives (critical 1-Wire; second poll block; paged) with why rejected. Acceptance test plan: cases for device add/remove, overflow, CRC error, no effect on production gating. CHANGELOG entry.
- [ ] **Step 3: Run `uv run pytest -q`, `uv run ruff check .`, `uv run ro-tools validate`, `uv run ro-tools generate --check`.** All green. Commit `docs(hardware): 1-Wire bus, ADR-0009`.
