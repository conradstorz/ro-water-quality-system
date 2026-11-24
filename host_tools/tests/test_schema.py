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
    assert (m.version_major, m.version_minor) == (1, 4)
    assert (m.input_start, m.input_count) == (100, 100)
    assert (m.status_start, m.status_count) == (220, 8)
    assert (m.names_start, m.names_count) == (240, 83)
    assert m.critical_validity_bits == (0, 1, 2, 3, 7)
    assert m.enums["ro_state"][4] == "production"
    assert m.enums["pump_commanded"] == {0: "off", 1: "on", 2: "unknown"}
    assert [r.address for r in m.input_registers] == sorted(r.address for r in m.input_registers)


def test_status_extension_flags_modelled():
    m = schema.load()
    assert m.status_require_sequence_progress is True


def test_register_defaults_and_flags():
    m = schema.load()
    by_name = {r.name: r for r in m.input_registers + m.holding_registers}
    assert by_name["device_id"].scale_divisor == 1
    assert by_name["reserved_135"].reserved is True
    assert by_name["feed_ec_us_cm_x10"].reserved is False
    assert by_name["ro_state"].enum == "ro_state"
    assert by_name["status_schema_major"].equals == 1
    fc = {f.code: f for f in m.fault_codes}
    assert fc[4001].state_dependent is True
    assert fc[1001].state_dependent is False


def _mutations():
    def bad_type(r):
        _reg(r, "input_registers", "module_status")["type"] = "u8"

    def bad_words(r):
        _reg(r, "input_registers", "uptime_seconds")["words"] = 1

    def overlap(r):
        _reg(r, "input_registers", "validity_mask")["address"] = 103

    def gap(r):
        r["input_registers"] = [x for x in r["input_registers"] if x["name"] != "reserved_139"]

    def outside(r):
        _reg(r, "input_registers", "reserved_139")["address"] = 140

    def bad_scale(r):
        _reg(r, "input_registers", "feed_ec_us_cm_x10")["scale_divisor"] = 100

    def zero_scale(r):
        _reg(r, "input_registers", "module_status")["scale_divisor"] = 0

    def unsuffixed_scale(r):
        _reg(r, "input_registers", "module_status")["scale_divisor"] = 10

    def dup_name(r):
        _reg(r, "holding_registers", "device_id")["name"] = "module_status"

    def bad_identifier(r):
        _reg(r, "holding_registers", "device_id")["name"] = "device-id"

    def bit_range(r):
        r["status_bits"][16] = "too_high"

    def critical_not_subset(r):
        r["critical_validity_bits"].append(12)

    def ext_start(r):
        r["controller_status_extension"]["start"] = 221

    def ext_count(r):
        r["controller_status_extension"]["count"] = 7

    def seq_progress_not_bool(r):
        r["controller_status_extension"]["require_sequence_progress"] = "yes"

    def seq_progress_missing(r):
        del r["controller_status_extension"]["require_sequence_progress"]

    def status_write_fc(r):
        r["controller_status_extension"]["function_code_write"] = 6

    def status_write_mode(r):
        r["controller_status_extension"]["write_mode"] = "partial_ok"

    def status_not_display_only(r):
        r["controller_status_extension"]["display_only"] = False

    def status_schema_major_mismatch(r):
        r["controller_status_extension"]["status_schema_major"] = 2

    def status_schema_register_missing(r):
        r["holding_registers"] = [
            x for x in r["holding_registers"] if x["name"] != "status_schema_major"
        ]

    def names_overlap_status(r):
        r["onewire_name_table"]["start"] = 225

    def names_gap(r):
        r["holding_registers"] = [
            x for x in r["holding_registers"] if x["name"] != "names_e7_label5"
        ]

    def names_read_only_inside_block(r):
        _reg(r, "holding_registers", "names_e3_rom2")["access"] = "read_only"

    def names_count_mismatch(r):
        r["onewire_name_table"]["count"] = 82

    def names_label_words_mismatch(r):
        r["onewire_name_table"]["label_words"] = 5

    def names_schema_major_mismatch(r):
        r["onewire_name_table"]["names_schema_major"] = 2

    def names_schema_register_missing(r):
        _reg(r, "holding_registers", "names_schema_major")["name"] = "names_header0"

    def names_write_fc(r):
        r["onewire_name_table"]["function_code_write"] = 6

    def names_write_mode(r):
        r["onewire_name_table"]["write_mode"] = "partial_ok"

    def names_not_display_only(r):
        r["onewire_name_table"]["display_only"] = False

    def names_missing_entry_count_max(r):
        del r["onewire_name_table"]["entry_count_max"]

    def names_missing_label_max_chars(r):
        del r["onewire_name_table"]["label_max_chars"]

    def names_label_max_chars_no_nul(r):
        r["onewire_name_table"]["label_max_chars"] = 12

    def names_label_max_chars_zero(r):
        r["onewire_name_table"]["label_max_chars"] = 0

    def names_section_missing(r):
        del r["onewire_name_table"]

    def bad_access(r):
        _reg(r, "holding_registers", "device_id")["access"] = "read_write"

    def bad_enum_ref(r):
        _reg(r, "holding_registers", "ro_state")["enum"] = "nope"

    def enum_value_range(r):
        r["enums"]["ro_state"][70000] = "huge"

    def dup_fault(r):
        r["fault_codes"].append(dict(r["fault_codes"][1]))

    def fault_source(r):
        r["fault_codes"][1]["source"] = "lcd"

    def fault_severity(r):
        r["fault_codes"][1]["default_severity"] = "fatal"

    def no_code_zero(r):
        r["fault_codes"] = r["fault_codes"][1:]

    def addressing(r):
        r["addressing"] = "one_based"

    def word_order(r):
        r["word_order_32bit"] = "low_word_first"

    def missing_key(r):
        del r["polling"]

    def dup_critical_bit(r):
        r["critical_validity_bits"].append(0)

    def critical_bit_is_list(r):
        r["critical_validity_bits"].append([1])

    def keyword_register(r):
        _reg(r, "holding_registers", "device_id")["name"] = "class"

    def soft_keyword_register(r):
        _reg(r, "holding_registers", "device_id")["name"] = "match"

    def enum_member_with_space(r):
        r["enums"]["ro_state"][4] = "pro duction"

    def enum_member_leading_digit(r):
        r["enums"]["ro_state"][4] = "1production"

    def enum_member_case_collision(r):
        r["enums"]["ro_state"][99] = "PRODUCTION"

    def enum_member_not_string(r):
        r["enums"]["ro_state"][4] = ["production"]

    def enum_name_leading_digit(r):
        r["enums"]["1bad"] = {0: "a"}

    def bit_name_with_space(r):
        r["status_bits"][5] = "not valid"

    def bit_name_case_collision(r):
        r["status_bits"][5] = "OPERATIONAL"

    def bit_name_not_string(r):
        r["status_bits"][5] = ["x"]

    def type_is_list(r):
        _reg(r, "input_registers", "module_status")["type"] = ["u16"]

    def access_is_mapping(r):
        _reg(r, "holding_registers", "device_id")["access"] = {"a": 1}

    def enum_is_list(r):
        _reg(r, "holding_registers", "ro_state")["enum"] = ["ro_state"]

    def fault_source_is_list(r):
        r["fault_codes"][1]["source"] = ["controller"]

    def fault_severity_is_list(r):
        r["fault_codes"][1]["default_severity"] = ["critical"]

    return [v for k, v in locals().items() if callable(v)]


@pytest.mark.parametrize("mutate", _mutations(), ids=lambda f: f.__name__)
def test_each_rule_rejects(raw, mutate):
    broken = copy.deepcopy(raw)
    mutate(broken)
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert exc.value.violations


def _violations(raw: dict, mutate) -> list[str]:
    broken = copy.deepcopy(raw)
    mutate(broken)
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    return exc.value.violations


def test_name_table_overlap_is_named(raw):
    def mutate(r):
        r["onewire_name_table"]["start"] = 225

    assert any("overlaps controller_status_extension" in v for v in _violations(raw, mutate))


def test_name_table_gap_is_named(raw):
    def mutate(r):
        r["holding_registers"] = [
            x for x in r["holding_registers"] if x["name"] != "names_e0_label0"
        ]

    assert _violations(raw, mutate) == [
        (
            "holding_registers: write_multiple_only addresses must equal "
            "controller_status_extension 220..227 plus onewire_name_table 240..322"
        )
    ]


def test_name_table_count_mismatch_is_named(raw):
    def mutate(r):
        r["onewire_name_table"]["entry_count_max"] = 7

    violations = _violations(raw, mutate)
    assert violations == [
        "onewire_name_table.count: 83 must equal 3 + entry_count_max * (4 + label_words) = 73"
    ]


def test_name_table_label_max_chars_leaves_room_for_nul(raw):
    def mutate(r):
        r["onewire_name_table"]["label_max_chars"] = 12

    violations = _violations(raw, mutate)
    assert violations == [
        (
            "onewire_name_table.label_max_chars: 12 must be 1..2 * label_words - 1 = 11 "
            "(the last label byte is always NUL)"
        )
    ]


def test_name_table_schema_major_mismatch_is_named(raw):
    def mutate(r):
        _reg(r, "holding_registers", "names_schema_major")["equals"] = 2

    assert _violations(raw, mutate) == [
        (
            "holding_registers.names_schema_major: equals 2 "
            "must match onewire_name_table.names_schema_major 1"
        )
    ]


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


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "map.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def _real_text() -> str:
    return schema.DEFAULT_MAP_PATH.read_text(encoding="utf-8")


def test_type_errors_never_escape_as_typeerror(raw):
    broken = copy.deepcopy(raw)
    _reg(broken, "input_registers", "module_status")["type"] = ["u16"]
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert any("type" in v and "module_status" in v for v in exc.value.violations)


def test_duplicate_critical_bit_names_the_bit(raw):
    broken = copy.deepcopy(raw)
    broken["critical_validity_bits"].append(0)
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert any("critical_validity_bits" in v and "duplicate" in v for v in exc.value.violations)


def test_duplicate_bit_index_in_yaml_is_rejected_at_load(tmp_path):
    text = _real_text().replace("  1: calibration_required\n", "  0: calibration_required\n", 1)
    with pytest.raises(schema.SchemaError) as exc:
        schema.load(_write(tmp_path, text))
    assert any("duplicate key 0" in v and "line" in v for v in exc.value.violations)


def test_duplicate_enum_value_in_yaml_is_rejected_at_load(tmp_path):
    lines = _real_text().splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("  ro_state:"))
    assert lines[start + 1].lstrip().startswith("0:"), "fixture assumption"
    lines.insert(start + 2, "    0: shadow\n")
    with pytest.raises(schema.SchemaError) as exc:
        schema.load(_write(tmp_path, "".join(lines)))
    assert any("duplicate key 0" in v for v in exc.value.violations)


def test_duplicate_top_level_key_is_rejected_at_load(tmp_path):
    text = _real_text() + "unit_id: 2\n"
    with pytest.raises(schema.SchemaError) as exc:
        schema.load(_write(tmp_path, text))
    assert any("duplicate key 'unit_id'" in v for v in exc.value.violations)


def test_all_duplicate_keys_are_collected(tmp_path):
    text = _real_text() + "unit_id: 2\nversion: {major: 1}\nversion: {major: 2}\n"
    with pytest.raises(schema.SchemaError) as exc:
        schema.load(_write(tmp_path, text))
    keys = " ".join(exc.value.violations)
    assert "'unit_id'" in keys and "'version'" in keys


@pytest.mark.parametrize("enum_name", ["fault_severity", "ro_state", "pump_commanded"])
@pytest.mark.parametrize("member", [["critical"], {"a": 1}, 3, None])
def test_malformed_enum_member_is_a_violation_not_a_crash(raw, enum_name, member):
    broken = copy.deepcopy(raw)
    key = max(broken["enums"][enum_name])
    broken["enums"][enum_name][key] = member
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert any(enum_name in v for v in exc.value.violations)


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [True]])
def test_state_dependent_must_be_a_boolean(raw, value):
    broken = copy.deepcopy(raw)
    broken["fault_codes"][1]["state_dependent"] = value
    with pytest.raises(schema.SchemaError) as exc:
        schema.parse(broken)
    assert any("state_dependent" in v for v in exc.value.violations)
