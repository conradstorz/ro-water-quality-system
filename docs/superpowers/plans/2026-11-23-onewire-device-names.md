# 1-Wire Device Names Implementation Plan

> **For agentic workers:** implement task-by-task with subagents. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let the owner name each 1-Wire device by ROM ID in a bindings file, show the names in host tools, and send them to the sensor node as a display-only name table (protocol 1.4) for the optional LCD.

**Spec:** `docs/superpowers/specs/2026-11-23-onewire-device-names-design.md` (approved 2026-11-23). It is normative; read it first.

**Tech stack:** Python 3.12 via `uv`, pytest (+hypothesis where useful), ruff, `ro-tools generate` codegen. Run host commands from `host_tools/`: `uv run pytest -q`, `uv run ruff check .`, `uv run ro-tools validate`, `uv run ro-tools generate --check`.

## Global constraints
- AGENTS.md rule 2: no existing register address, scale, signedness or access changes. Only additions plus version 1.3 → 1.4.
- Names are display-only and monitoring-only. They never touch `validity_bits`, `critical_validity_bits`, node health or `production_permitted`.
- Name table layout (exact): holding 240 `names_schema_major` (u16, equals 1), 241 `names_revision` (u16), 242 `names_entry_count` (u16, 0-8); entry n (0..7) base = 243 + 10n: `names_eN_rom0..rom3` (u16, same 64-bit ROM encoding as input slots `onewire_sN_rom0..3`), `names_eN_label0..label5` (u16, 2 ASCII chars per word, high byte first, NUL-padded). Block is 240-322, 83 registers, FC16 atomic full-block write, FC03 read-back allowed, access `write_multiple_only`.
- Node validation (reject the whole write, keep the previous table): schema_major != 1; entry_count > 8; for n < count: ROM CRC bad, label empty, a char outside the LCD-safe set, or a NUL followed by a non-NUL; duplicate ROM among used entries; any non-zero word in entries n >= count.
- LCD-safe set: 0x20-0x7D except 0x5C and 0x7E. Bindings-file labels additionally: 1-12 chars, no leading/trailing space, unique. Roles: `^[a-z][a-z0-9_]{0,31}$`, unique. ROM text: 16 hex digits, family byte first, CRC byte last, CRC checked, unique.
- Python style: type annotations, Sphinx docstrings, pathlib, Loguru in host tools. Do not chain shell commands with `&&`. Commits end with `Assisted-by: <model actually writing it> (Claude Code)` and no Co-Authored-By line.

---

### Task 1: ROM text format, bindings file, binding label
**Files:** `host_tools/src/ro_tools/onewire.py`, new `host_tools/src/ro_tools/onewire_names.py`, `host_tools/src/ro_tools/monitor.py`, new `config/onewire_bindings.yaml`, tests (`test_onewire.py`, new `test_onewire_names.py`, `test_monitor_onewire.py`).
- [ ] `format_rom(rom: int) -> str` and `parse_rom(text: str) -> int` in `onewire.py`, next to `make_rom`. Wire order: the text's first byte is the family code (the integer's LOW byte), last byte is the CRC (HIGH byte). `parse_rom` accepts case-insensitive 16 hex digits only, raises `ValueError` on bad length/chars/CRC. Round-trip test, including with hypothesis over `make_rom(family, serial)`.
- [ ] `onewire_names.py`: `load_bindings(path: Path) -> tuple[OneWireBinding, ...]` and `validate_bindings_data(data) -> list[str]` (all violations, not first only), applying every rule in Global constraints. `schema: 1` required. Empty `devices: []` is valid.
- [ ] `OneWireBinding` gains `label: str` (required). Update `evaluate_onewire` callers/tests; behavior otherwise unchanged.
- [ ] `config/onewire_bindings.yaml`: `schema: 1`, `devices: []`, with a commented example entry. A test loads it and expects no violations.
- [ ] Full suite + ruff green. Commit `feat(onewire): ROM text format and bindings file`.

### Task 2: Protocol 1.4 name table in the register map
**Files:** `protocol/register_map.yaml`, `host_tools/src/ro_tools/schema.py`, `host_tools/src/ro_tools/codegen.py`, `host_tools/src/ro_tools/generated/registers.py` (regenerated), tests (new `test_protocol_v14.py`, `test_schema.py`, `test_docs_consistency.py`, any test pinning minor 3).
- [ ] Write failing `test_protocol_v14.py`: minor == 4; every 1.3 input and holding register keeps address/type/scale/access (literal dict of a representative set: 100, 115, 131, 133, 134, 140, 144, 199, 200, 202, 220, 227); 240-322 exact layout from Global constraints; all new registers `write_multiple_only`; input window still 100-199; status extension still 220-227.
- [ ] YAML: version minor 4; 83 holding registers; new top-level section `onewire_name_table: {start: 240, count: 83, function_code_write: 16, write_mode: atomic_full_block_only, names_schema_major: 1, entry_count_max: 8, label_words: 6, display_only: true}` (generate entries with a throwaway script in the scratchpad, not committed).
- [ ] `schema.py`: parse the new section into `RegisterMap`; the `write_multiple_only` check becomes "write_multiple_only addresses == union of controller_status_extension and onewire_name_table ranges", the two ranges must not overlap, and each range must be fully `write_multiple_only`. Add schema tests for overlap and gap violations.
- [ ] Codegen: export constants for the new block (start, count, entry stride 10, label words 6, entry max 8, schema major) the way the status-extension constants are exported. `uv run ro-tools generate`, then `--check`.
- [ ] Scope `test_status_extension_table_matches_yaml` to 220-227 only. Update tests pinning minor 3.
- [ ] Full suite, ruff, validate, generate --check green. Commit `feat(protocol): 1.4 1-Wire name table 240-322`.

### Task 3: Table encode/decode, node validation, subset selection, LCD reference renderer
**Files:** `host_tools/src/ro_tools/onewire_names.py`, `host_tools/tests/test_onewire_names.py`.
- [ ] `NameEntry(rom: int, label: str)`; `encode_name_table(entries, revision) -> list[int]` (83 words; raises on > 8 entries or invalid label); `validate_name_table(words) -> list[str]` (node-side rules exactly as Global constraints; empty list means accept); `decode_name_table(words) -> tuple[int, tuple[NameEntry, ...]]` (revision, entries; raises on invalid).
- [ ] `select_for_node(bindings, slots) -> tuple[NameEntry, ...]`: bindings whose ROM is in the node's present slots, sorted by ROM, at most 8.
- [ ] `bindings_revision(path) -> int`: CRC-16/MODBUS of the file bytes.
- [ ] `render_onewire_rows(slots, entries) -> list[str]`: reference LCD rows per spec section 3 (label 12 + space + 7-char value; DS2438 two rows; unnamed `?FF-SSSS`; invalid `    ---`; unfittable `    ERR`; unknown family: label row with `    ---`). Property test: every row is exactly 20 chars and LCD-safe for random slots/labels.
- [ ] Tests for every reject rule and round-trip (hypothesis). Commit `feat(onewire): name table codec, validation and LCD reference rows`.

### Task 4: Simulator, client and isolation
**Files:** `host_tools/src/ro_tools/sim/register_bank.py`, `sim/server.py`, `sim/presets.py`, `client.py`, tests (`test_register_bank.py`, `test_server.py`, `test_client_integration.py`, `test_monitor_onewire.py` or new).
- [ ] Register bank: accepts an FC16 write of exactly 240-322, validates with `validate_name_table`, stores atomically, logs the rejection reason (like status writes, `bank.last_rejection`), keeps the prior table on reject. FC03 read-back returns the stored table (all zero after construction / `reboot()`). Partial or misaligned writes rejected with ILLEGAL_DATA_ADDRESS or ILLEGAL_DATA_VALUE consistent with how the status block is handled.
- [ ] Bank gets a flag to emulate a protocol 1.3 node (no name table: ILLEGAL_ADDRESS on 240-322).
- [ ] Client: `write_name_table(entries, revision)` and `read_name_table() -> tuple[int, tuple[NameEntry, ...]] | None` (None for an all-zero/never-written table), with the existing reply verification.
- [ ] Preset `onewire_named`: the existing DS18B20 + DS2438 pair; tests use matching bindings.
- [ ] Isolation tests: with a rejected write, an unsupported (1.3) node, and a successful write, `evaluate` and `production_permitted` results are identical to the no-write case.
- [ ] Commit `feat(sim): accept and read back 1-Wire name table`.

### Task 5: CLI and controller push model
**Files:** `host_tools/src/ro_tools/cli.py`, `host_tools/src/ro_tools/onewire_names.py` (push policy), `host_tools/README.md`, tests (`test_cli.py` or new `test_cli_onewire.py`).
- [ ] `NamePushPolicy` (pure, no I/O): given previous and current (`boot_counter`, `onewire_scan_generation`, bindings revision, supported flag), decide push / skip; ILLEGAL_ADDRESS marks unsupported until `boot_counter` changes. Unit tests for each trigger.
- [ ] `ro-tools onewire scan --unit-id N [--bindings PATH]`: one row per present slot: ROM text, family name, reading(s), role/label or `UNBOUND`; then a YAML stub for every unbound ROM (`- rom: ...\n  role: TODO\n  label: TODO`).
- [ ] `ro-tools onewire validate [--bindings PATH]`: prints violations, exit 1 on any.
- [ ] `ro-tools onewire push --unit-id N [--bindings PATH]`: select entries for the node, write, read back, report mismatch (exit 1). Default bindings path `config/onewire_bindings.yaml` relative to repo root.
- [ ] CLI tests against the in-process simulator (follow existing CLI test patterns). README section. Commit `feat(cli): onewire scan, validate and push`.

### Task 6: Docs
**Files:** new `docs/decisions/ADR-0011-onewire-device-names.md`, new `protocol/ONEWIRE_NAME_TABLE.md`, `protocol/REGISTER_MAP_REFERENCE.md`, `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`, `docs/specs/SENSOR_NODE_LCD_SPEC.md`, `docs/specs/EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md`, `docs/test/LCD_FAULT_PRIORITY_TESTS.md`, `docs/test/ACCEPTANCE_TEST_PLAN.md`, `AGENTS.md` (one line: name table is display-only like the status block), `CHANGELOG.md`, `host_tools/tests/test_docs_consistency.py`.
- [ ] ADR-0011 Proposed: decision, why a display-only write is allowed despite the no-writable-calibration rule, alternatives rejected (per-value entries: 16 entries exceed one FC16 write; node-side name storage in NVS: two sources of truth; names in the input block: wrong direction), deferred firmware embedding.
- [ ] `ONEWIRE_NAME_TABLE.md`: table of 240-322 plus write contract; a docs-consistency test checks its table against the YAML (like the status extension test).
- [ ] LCD specs: 1-Wire pages in NORMAL rotation after diagnostics, row layout, unnamed format, charset (A00 assumption). LCD fault tests: names never change priority; 1-Wire pages never preempt.
- [ ] Acceptance plan: rejected write keeps the prior table; reboot clears table and controller re-pushes; 1.3 node reports unsupported without affecting production.
- [ ] CHANGELOG entry. Full suite, ruff, validate, generate --check green. Commit `docs(onewire): device names, ADR-0011`.
