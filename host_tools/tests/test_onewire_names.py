"""Tests for the 1-Wire bindings file (config/onewire_bindings.yaml)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ro_tools.monitor import OneWireBinding
from ro_tools.onewire import FAMILY_DS18B20, FAMILY_DS2438, format_rom, make_rom
from ro_tools.onewire_names import (
    DEFAULT_BINDINGS_PATH,
    BindingsError,
    is_lcd_safe,
    load_bindings,
    validate_bindings_data,
)

ROM_A = make_rom(FAMILY_DS18B20, 0x1001)
ROM_B = make_rom(FAMILY_DS2438, 0x1002)
#: Literal ROM text used in the commented example of the real bindings file.
EXAMPLE_ROM_TEXT = "28FF1B2C3D5F4EDE"


def _dev(rom: int = ROM_A, role: str = "tank_temp", label: str = "Tank temp") -> dict:
    return {"rom": format_rom(rom), "role": role, "label": label}


def _data(*devices: object) -> dict:
    return {"schema": 1, "devices": list(devices)}


def _one_violation(data: object, *needles: str) -> None:
    bad = validate_bindings_data(data)
    assert len(bad) == 1, bad
    for needle in needles:
        assert needle in bad[0], bad


def test_valid_two_devices() -> None:
    data = _data(_dev(), _dev(ROM_B, "feed_temp", "Feed temp"))
    assert validate_bindings_data(data) == []


def test_empty_devices_is_valid() -> None:
    assert validate_bindings_data({"schema": 1, "devices": []}) == []


@pytest.mark.parametrize("data", [None, [], "schema: 1", 1])
def test_top_level_must_be_mapping(data: object) -> None:
    _one_violation(data, "top level")


@pytest.mark.parametrize("schema", [None, 0, 2, "1", True, 1.0])
def test_schema_must_be_one(schema: object) -> None:
    _one_violation({"schema": schema, "devices": []}, "schema")


def test_schema_missing() -> None:
    _one_violation({"devices": []}, "schema")


def test_devices_missing_or_not_list() -> None:
    _one_violation({"schema": 1}, "devices")
    _one_violation({"schema": 1, "devices": None}, "devices")
    _one_violation({"schema": 1, "devices": {"a": 1}}, "devices")


def test_unknown_top_level_key() -> None:
    _one_violation(_data() | {"extra": 1}, "extra")


def test_device_must_be_mapping() -> None:
    _one_violation(_data("28AB89674523015A"), "devices[0]")


def test_device_missing_and_unknown_keys() -> None:
    dev = _dev()
    del dev["label"]
    _one_violation(_data(dev), "devices[0]", "label")
    _one_violation(_data(_dev() | {"note": "x"}), "devices[0]", "note")


@pytest.mark.parametrize(
    "rom",
    [
        "28AB89674523015B",  # CRC wrong
        "28AB8967452301",  # too short
        "28AB89674523015G",  # non-hex
        1234567890123456,  # YAML int (unquoted all-digit text)
        None,
    ],
)
def test_bad_rom(rom: object) -> None:
    _one_violation(_data(_dev() | {"rom": rom}), "devices[0].rom")


def test_duplicate_rom_is_case_insensitive() -> None:
    other = _dev(ROM_A, "other", "Other") | {"rom": format_rom(ROM_A).lower()}
    _one_violation(_data(_dev(), other), "devices[1].rom", "duplicate", "devices[0]")


@pytest.mark.parametrize(
    "role", ["Tank", "1tank", "_tank", "tank-temp", "tank temp", "", "a" * 33, 5, None]
)
def test_bad_role(role: object) -> None:
    _one_violation(_data(_dev(role=role)), "devices[0].role")  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["a", "a" * 32, "t1_x_9"])
def test_good_role(role: str) -> None:
    assert validate_bindings_data(_data(_dev(role=role))) == []


def test_duplicate_role() -> None:
    _one_violation(_data(_dev(), _dev(ROM_B, "tank_temp", "Other")), "devices[1].role", "duplicate")


@pytest.mark.parametrize(
    "label",
    [
        "",
        "x" * 13,
        " Tank",
        "Tank ",
        "back\\slash",
        "tilde~",
        "tab\there",
        "café",
        "\x7f",
        123,
        None,
    ],
)
def test_bad_label(label: object) -> None:
    bad = validate_bindings_data(_data(_dev(label=label)))  # type: ignore[arg-type]
    assert bad and all("devices[0].label" in v for v in bad), bad


@pytest.mark.parametrize("label", ["x", "x" * 12, "A b{}|!", "-12.3 C #1"])
def test_good_label(label: str) -> None:
    assert validate_bindings_data(_data(_dev(label=label))) == []


def test_duplicate_label() -> None:
    _one_violation(
        _data(_dev(), _dev(ROM_B, "feed_temp", "Tank temp")), "devices[1].label", "duplicate"
    )


def test_all_violations_reported() -> None:
    data = {
        "schema": 2,
        "devices": [
            {"rom": "bad", "role": "Bad", "label": ""},
            _dev(),
            _dev(ROM_A, "tank_temp", "Tank temp"),
        ],
    }
    bad = validate_bindings_data(data)
    assert len(bad) == 7, bad


def test_lcd_safe_set() -> None:
    safe = {chr(c) for c in range(0x110) if is_lcd_safe(chr(c))}
    assert safe == {chr(c) for c in range(0x20, 0x7E)} - {"\\"}


def test_load_bindings(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(
        "schema: 1\ndevices:\n"
        f'  - rom: "{format_rom(ROM_A)}"\n    role: tank_temp\n    label: Tank temp\n'
        f"  - rom: '{format_rom(ROM_B).lower()}'\n    role: feed_temp\n    label: Feed temp\n",
        encoding="utf-8",
    )
    assert load_bindings(p) == (
        OneWireBinding("tank_temp", ROM_A, "Tank temp"),
        OneWireBinding("feed_temp", ROM_B, "Feed temp"),
    )


def test_unquoted_all_digit_rom_asks_for_quotes(tmp_path: Path) -> None:
    assert format_rom(ROM_A).isdigit()  # YAML would load this text as an int
    p = tmp_path / "b.yaml"
    p.write_text(
        f"schema: 1\ndevices:\n  - rom: {format_rom(ROM_A)}\n    role: a\n    label: x\n",
        encoding="utf-8",
    )
    with pytest.raises(BindingsError, match="quote it"):
        load_bindings(p)


def test_load_bindings_raises_value_error_with_all_violations(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(
        "schema: 1\ndevices:\n  - rom: 28AB89674523015B\n    role: Bad\n    label: ok\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as exc:
        load_bindings(p)
    assert isinstance(exc.value, BindingsError)
    assert len(exc.value.violations) == 2


def test_load_bindings_rejects_duplicate_keys(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text(
        "schema: 1\ndevices:\n"
        f'  - rom: "{format_rom(ROM_A)}"\n    role: a\n    role: b\n    label: x\n',
        encoding="utf-8",
    )
    with pytest.raises(BindingsError) as exc:
        load_bindings(p)
    assert any("duplicate key 'role'" in v for v in exc.value.violations)


def test_load_bindings_rejects_bad_yaml(tmp_path: Path) -> None:
    p = tmp_path / "b.yaml"
    p.write_text("schema: 1\ndevices: [\n", encoding="utf-8")
    with pytest.raises(BindingsError, match="invalid YAML"):
        load_bindings(p)


def test_real_bindings_file_is_valid() -> None:
    raw = yaml.safe_load(DEFAULT_BINDINGS_PATH.read_text(encoding="utf-8"))
    assert validate_bindings_data(raw) == []
    assert load_bindings(DEFAULT_BINDINGS_PATH) == ()


def test_real_bindings_file_commented_example_is_valid() -> None:
    lines = DEFAULT_BINDINGS_PATH.read_text(encoding="utf-8").splitlines()
    start = lines.index("# devices:")
    example: list[str] = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        example.append(line.removeprefix("# "))
    data = {"schema": 1} | yaml.safe_load("\n".join(example))
    assert validate_bindings_data(data) == []
    assert data["devices"][0]["rom"] == EXAMPLE_ROM_TEXT
    assert EXAMPLE_ROM_TEXT == format_rom(make_rom(FAMILY_DS18B20, 0x4E5F3D2C1BFF))
