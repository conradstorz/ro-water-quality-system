"""Tests for 1-Wire names: bindings file, name table codec and LCD reference rows."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st
from loguru import logger

from ro_tools.generated.registers import (
    NAMES_COUNT,
    NAMES_ENTRY_BASE,
    NAMES_ENTRY_STRIDE,
    NAMES_START,
    Snapshot,
)
from ro_tools.monitor import OneWireBinding
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    OneWireDevice,
    SlotReading,
    SlotStatus,
    decode_slots,
    encode_onewire,
    format_rom,
    make_rom,
    parse_rom,
    rom_family,
)
from ro_tools.onewire_names import (
    DEFAULT_BINDINGS_PATH,
    BindingsError,
    NameEntry,
    NameTableError,
    bindings_revision,
    decode_name_table,
    encode_name_table,
    format_temperature,
    is_lcd_safe,
    load_bindings,
    paginate,
    render_onewire_rows,
    select_for_node,
    unnamed_label,
    validate_bindings_data,
    validate_name_table,
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
        "x" * 12,
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


@pytest.mark.parametrize("label", ["x", "x" * 11, "A b{}|!", "-12.3 C #1"])
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


def test_all_zero_rom_rejected() -> None:
    # CRC-8 of seven zero bytes is 0, so parse_rom accepts it; the bindings do not.
    data = _data({"rom": "0000000000000000", "role": "tank_temp", "label": "Tank temp"})
    _one_violation(data, "devices[0].rom", "all-zero")


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


# --------------------------------------------------------------------------------------
# Name table codec and node-side validation
# --------------------------------------------------------------------------------------

E0 = NAMES_ENTRY_BASE - NAMES_START  # table offset of entry 0
_SAFE_CHARS = "".join(chr(c) for c in range(0x20, 0x7E) if c != 0x5C)

_labels = st.text(alphabet=_SAFE_CHARS, min_size=1, max_size=11)
_roms = st.builds(make_rom, st.integers(0, 0xFF), st.integers(0, (1 << 48) - 1)).filter(bool)


def _table(n: int = 2) -> list[int]:
    entries = [NameEntry(make_rom(FAMILY_DS18B20, 0x100 + i), f"Dev {i}") for i in range(n)]
    return encode_name_table(entries, revision=0x1234)


def _one_table_violation(words: list[int], *needles: str) -> None:
    bad = validate_name_table(words)
    assert len(bad) == 1, bad
    for needle in needles:
        assert needle in bad[0], bad


def test_encode_layout() -> None:
    rom = make_rom(FAMILY_DS18B20, 0x0123456789AB)
    words = encode_name_table([NameEntry(rom, "Outside")], revision=7)
    assert len(words) == NAMES_COUNT == 83
    assert words[:3] == [1, 7, 1]
    assert words[E0 : E0 + 4] == [(rom >> s) & 0xFFFF for s in (48, 32, 16, 0)]
    assert words[E0 + 4 : E0 + 10] == [0x4F75, 0x7473, 0x6964, 0x6500, 0, 0]
    assert all(w == 0 for w in words[E0 + 10 :])
    assert validate_name_table(words) == []


def test_encode_empty_table() -> None:
    words = encode_name_table([], revision=0)
    assert words == [1] + [0] * 82
    assert decode_name_table(words) == (0, ())


def test_table_rom_words_match_input_slot_encoding() -> None:
    roms = [make_rom(FAMILY_DS18B20, 0xA1B2C3D4E5F6), make_rom(FAMILY_DS2438, 0xFFFFFFFFFFFF)]
    words = encode_name_table([NameEntry(r, "x") for r in roms], revision=0)
    fields = encode_onewire([OneWireDevice(r) for r in roms])
    for n, rom in enumerate(sorted(roms)):
        slot = [fields[f"onewire_s{n}_rom{w}"] for w in range(4)]
        idx = roms.index(rom)
        base = E0 + NAMES_ENTRY_STRIDE * idx
        assert words[base : base + 4] == slot


@given(rom=_roms)
def test_table_rom_words_match_input_slot_encoding_property(rom: int) -> None:
    words = encode_name_table([NameEntry(rom, "x")], revision=0)
    fields = encode_onewire([OneWireDevice(rom)])
    assert words[E0 : E0 + 4] == [fields[f"onewire_s0_rom{w}"] for w in range(4)]
    (slot,) = decode_slots(Snapshot(**fields))
    assert slot.rom == rom


@given(
    entries=st.lists(st.builds(NameEntry, _roms, _labels), max_size=8, unique_by=lambda e: e.rom),
    revision=st.integers(0, 0xFFFF),
)
def test_round_trip(entries: list[NameEntry], revision: int) -> None:
    words = encode_name_table(entries, revision)
    assert len(words) == 83
    assert all(0 <= w <= 0xFFFF for w in words)
    assert validate_name_table(words) == []
    assert decode_name_table(words) == (revision, tuple(entries))


@pytest.mark.parametrize(
    ("entries", "revision", "needle"),
    [
        ([NameEntry(make_rom(0x28, i), "a") for i in range(9)], 0, "at most 8"),
        ([], -1, "revision"),
        ([], 0x10000, "revision"),
        ([NameEntry(ROM_A, "")], 0, "1-11"),
        ([NameEntry(ROM_A, "x" * 12)], 0, "1-11"),
        ([NameEntry(ROM_A, "a\\b")], 0, "LCD-safe"),
        ([NameEntry(ROM_A, "a~b")], 0, "LCD-safe"),
        ([NameEntry(ROM_A, "a\0b")], 0, "LCD-safe"),
        ([NameEntry(ROM_A, "café")], 0, "LCD-safe"),
        ([NameEntry(ROM_A ^ 1, "a")], 0, "CRC"),
        ([NameEntry(1 << 64, "a")], 0, "64 bits"),
        ([NameEntry(0, "a")], 0, "all-zero"),
        ([NameEntry(ROM_A, "a"), NameEntry(ROM_A, "b")], 0, "duplicate"),
    ],
)
def test_encode_rejects(entries: list[NameEntry], revision: int, needle: str) -> None:
    with pytest.raises(ValueError, match=needle):
        encode_name_table(entries, revision)


def test_encode_allows_edge_spaces() -> None:
    words = encode_name_table([NameEntry(ROM_A, " Tank ")], revision=0)
    assert decode_name_table(words)[1] == (NameEntry(ROM_A, " Tank "),)


@pytest.mark.parametrize("length", [0, 82, 84])
def test_validate_wrong_length(length: int) -> None:
    _one_table_violation([0] * length, "83 words")


@pytest.mark.parametrize("major", [0, 2])
def test_validate_schema_major(major: int) -> None:
    words = _table()
    words[0] = major
    _one_table_violation(words, "names_schema_major")


def test_validate_entry_count_over_8() -> None:
    words = _table(8)
    words[2] = 9
    _one_table_violation(words, "names_entry_count 9")


def test_validate_bad_rom_crc() -> None:
    words = _table()
    words[E0 + NAMES_ENTRY_STRIDE + 3] ^= 0x0100
    _one_table_violation(words, "entry 1", "CRC")


def test_validate_empty_label() -> None:
    words = _table()
    words[E0 + 4 : E0 + 10] = [0] * 6
    _one_table_violation(words, "entry 0", "empty")


@pytest.mark.parametrize("byte", [0x5C, 0x7E, 0x7F, 0x80, 0x1F, 0xFF, 0x01])
@pytest.mark.parametrize("high", [True, False])
def test_validate_unsafe_label_byte(byte: int, high: bool) -> None:
    words = _table()
    words[E0 + 4] = (byte << 8) | 0x41 if high else 0x4100 | byte
    _one_table_violation(words, "entry 0", f"0x{byte:02X}")


def test_validate_embedded_nul_across_words() -> None:
    words = _table()
    words[E0 + 4 : E0 + 10] = [0x4100, 0x4142, 0, 0, 0, 0]
    _one_table_violation(words, "embedded NUL")


def test_validate_embedded_nul_within_word() -> None:
    words = _table()
    words[E0 + 4 : E0 + 10] = [0x0041, 0, 0, 0, 0, 0]
    bad = validate_name_table(words)
    assert any("empty" in b for b in bad), bad
    assert any("embedded NUL" in b for b in bad), bad


def test_validate_full_11_char_label_ok() -> None:
    words = encode_name_table([NameEntry(ROM_A, "ABCDEFGHIJK")], revision=0)
    assert words[E0 + 9] == 0x4B00  # label5: 11th char in the high byte, NUL low byte
    assert validate_name_table(words) == []
    assert decode_name_table(words)[1] == (NameEntry(ROM_A, "ABCDEFGHIJK"),)


def test_validate_12_char_label_rejected() -> None:
    words = encode_name_table([NameEntry(ROM_A, "ABCDEFGHIJK")], revision=0)
    words[E0 + 9] = 0x4B4C  # "KL": the 12th byte (low byte of label5) is not NUL
    _one_table_violation(words, "entry 0", "longer than 11")


def test_validate_12th_byte_alone_rejected() -> None:
    words = _table()
    words[E0 + 9] = 0x004C  # NUL then "L": too long and an embedded NUL
    bad = validate_name_table(words)
    assert any("longer than 11" in b for b in bad), bad
    assert any("embedded NUL" in b for b in bad), bad


def test_validate_all_zero_rom_rejected() -> None:
    words = _table()
    words[E0 : E0 + 4] = [0, 0, 0, 0]
    _one_table_violation(words, "entry 0", "all-zero")


def test_validate_accepts_edge_spaces() -> None:
    words = _table()
    words[E0 + 4 : E0 + 10] = [0x2041, 0x2000, 0, 0, 0, 0]  # " A "
    assert validate_name_table(words) == []


def test_validate_duplicate_rom() -> None:
    words = _table()
    words[E0 + NAMES_ENTRY_STRIDE : E0 + NAMES_ENTRY_STRIDE + 4] = words[E0 : E0 + 4]
    _one_table_violation(words, "entry 1", "duplicate")


@pytest.mark.parametrize("offset", [0, 3, 4, 9])
def test_validate_unused_entry_not_zero(offset: int) -> None:
    words = _table(2)
    words[E0 + 2 * NAMES_ENTRY_STRIDE + offset] = 1
    _one_table_violation(words, "entry 2", "not all zero")


def test_validate_reports_every_violation() -> None:
    words = _table(2)
    words[0] = 3
    words[E0 + 3] ^= 1
    words[-1] = 5
    assert len(validate_name_table(words)) == 3


def test_validate_rejects_non_u16_word() -> None:
    words = _table()
    words[1] = 0x10000
    _one_table_violation(words, "outside u16")


def test_decode_raises_with_violations() -> None:
    words = _table()
    words[0] = 2
    with pytest.raises(NameTableError) as info:
        decode_name_table(words)
    assert isinstance(info.value, ValueError)
    assert len(info.value.violations) == 1


# --------------------------------------------------------------------------------------
# Per-node selection and revision
# --------------------------------------------------------------------------------------

P = SlotStatus.PRESENT
PV = SlotStatus.PRESENT | SlotStatus.VALID


def _slot(
    rom: int, status: SlotStatus = PV, primary: int = 0, secondary: int = 0, i: int = 0
) -> SlotReading:
    return SlotReading(rom, primary, secondary, status, i)


def test_select_for_node_filters_and_sorts() -> None:
    r1, r2, r3, r4 = (make_rom(FAMILY_DS18B20, s) for s in (5, 1, 9, 3))
    bindings = [
        OneWireBinding("a", r1, "A"),
        OneWireBinding("b", r2, "B"),
        OneWireBinding("c", r3, "C"),
        OneWireBinding("d", r4, "D"),
    ]
    slots = [
        _slot(r1, PV),
        _slot(r2, P),  # present but invalid still counts
        _slot(r3, SlotStatus.MISSING),  # not present
        _slot(make_rom(FAMILY_DS18B20, 77), PV),  # unbound
    ]
    got = select_for_node(bindings, slots)
    assert got == tuple(sorted([NameEntry(r1, "A"), NameEntry(r2, "B")], key=lambda e: e.rom))


def test_select_for_node_truncates_to_8() -> None:
    roms = [make_rom(FAMILY_DS18B20, s) for s in range(10)]
    bindings = [OneWireBinding(f"r{i}", r, f"L{i}") for i, r in enumerate(roms)]
    messages: list[str] = []
    handler = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        got = select_for_node(bindings, [_slot(r) for r in roms])
    finally:
        logger.remove(handler)
    assert [e.rom for e in got] == sorted(roms)[:8]
    assert any("first 8" in m for m in messages)


def test_select_for_node_empty() -> None:
    assert select_for_node([], [_slot(ROM_A)]) == ()


def test_bindings_revision(tmp_path: Path) -> None:
    path = tmp_path / "b.yaml"
    path.write_bytes(b"123456789")
    assert bindings_revision(path) == 0x4B37
    path.write_bytes(b"123456788")
    assert bindings_revision(path) != 0x4B37


def test_bindings_revision_real_file_is_u16() -> None:
    assert 0 <= bindings_revision() <= 0xFFFF


# --------------------------------------------------------------------------------------
# Reference LCD rows
# --------------------------------------------------------------------------------------

DS18 = make_rom(FAMILY_DS18B20, 0x00003D2C1B4A)
DS24 = make_rom(FAMILY_DS2438, 0x0000000012AB)


@pytest.mark.parametrize(
    ("centi", "text"),
    [
        (2150, "21.5C"),
        (2155, "21.6C"),
        (2154, "21.5C"),
        (-1230, "-12.3C"),
        (-2155, "-21.6C"),
        (-4, "0.0C"),
        (-5, "-0.1C"),
        (0, "0.0C"),
        (12500, "125.0C"),
        (-32768, "-327.7C"),
        (32767, "327.7C"),
    ],
)
def test_format_temperature(centi: int, text: str) -> None:
    assert format_temperature(centi) == text


def test_unnamed_label() -> None:
    # Bindings-file example ROM text; the serial's low 16 bits are 0x1BFF.
    assert unnamed_label(parse_rom(EXAMPLE_ROM_TEXT)) == "?28-1BFF"
    assert unnamed_label(DS24) == "?26-12AB"


def test_render_named_ds18b20() -> None:
    rows = render_onewire_rows([_slot(DS18, primary=2150)], [NameEntry(DS18, "Outside air")])
    assert rows == ["Outside air   21.5C "]


def test_render_unnamed_negative() -> None:
    rows = render_onewire_rows([_slot(DS18, primary=-1230)], [])
    assert rows == ["?28-1B4A     -12.3C "]


def test_render_ds2438_two_rows() -> None:
    rows = render_onewire_rows(
        [_slot(DS24, primary=12500, secondary=3300)], [NameEntry(DS24, "Battery")]
    )
    assert rows == ["Battery      125.0C ", "             3300mV "]


def test_render_ds2438_mv_err() -> None:
    rows = render_onewire_rows([_slot(DS24, primary=0, secondary=-12345)], [])
    assert rows == ["?26-12AB       0.0C ", "                ERR "]


@pytest.mark.parametrize(
    "status",
    [
        P,
        PV | SlotStatus.STALE,
        PV | SlotStatus.CRC_ERROR,
        PV | SlotStatus.MISSING,
        SlotStatus(int(PV) | 0x40),  # unknown bit: unusable, same as the monitor
    ],
)
def test_render_unusable_shows_dashes(status: SlotStatus) -> None:
    rows = render_onewire_rows([_slot(DS24, status, 2150, 3300)], [NameEntry(DS24, "Tank")])
    assert rows == ["Tank" + " " * 12 + "--- ", " " * 16 + "--- "]


def test_render_unknown_family_one_row() -> None:
    rom = make_rom(0x10, 0xBEEF)
    status = P | SlotStatus.UNSUPPORTED_FAMILY
    assert render_onewire_rows([_slot(rom, status)], [NameEntry(rom, "Old sensor")]) == [
        "Old sensor      --- "
    ]
    assert render_onewire_rows([_slot(rom, PV)], []) == ["?10-BEEF        --- "]


def test_render_skips_not_present_and_keeps_slot_order() -> None:
    other = make_rom(FAMILY_DS18B20, 1)
    slots = [
        _slot(DS18, PV, 100, i=0),
        _slot(other, SlotStatus.MISSING, i=1),
        _slot(DS24, PV, 200, 5, i=2),
    ]
    rows = render_onewire_rows(slots, [])
    assert [r[:8] for r in rows] == ["?28-1B4A", "?26-12AB", "        "]


def test_render_rejects_bad_entry_label() -> None:
    with pytest.raises(ValueError, match="LCD-safe"):
        render_onewire_rows([], [NameEntry(DS18, "a~")])
    with pytest.raises(ValueError, match="1-11"):
        render_onewire_rows([], [NameEntry(DS18, "x" * 12)])


def test_render_indicator_in_column_20() -> None:
    rows = render_onewire_rows(
        [_slot(DS24, primary=2150, secondary=3300)], [NameEntry(DS24, "ABCDEFGHIJK")], "!"
    )
    assert rows == ["ABCDEFGHIJK   21.5C!", "             3300mV!"]


@pytest.mark.parametrize("indicator", ["", "ab", "~", "\\", "", "°"])
def test_render_rejects_bad_indicator(indicator: str) -> None:
    with pytest.raises(ValueError, match="indicator"):
        render_onewire_rows([], [], indicator)


def test_paginated_unnamed_rows_fit() -> None:
    slots = [
        _slot(make_rom(FAMILY_DS2438, 0xFFFF00 + i), PV, -32768, -32768, i=i) for i in range(8)
    ]
    pages = paginate(render_onewire_rows(slots, [], "*"))
    assert len(pages) == 4
    for page in pages:
        assert len(page) == 4
        for row in page:
            assert len(row) == 20 and row[19] == "*", repr(row)


def test_paginate() -> None:
    rows = [str(i) for i in range(9)]
    assert paginate(rows) == [["0", "1", "2", "3"], ["4", "5", "6", "7"], ["8"]]
    assert paginate([]) == []
    with pytest.raises(ValueError):
        paginate(rows, 0)


_slot_strategy = st.builds(
    SlotReading,
    rom=st.one_of(
        _roms,
        st.builds(make_rom, st.sampled_from([FAMILY_DS18B20, FAMILY_DS2438]), st.integers(0, 99)),
    ),
    primary=st.integers(-32768, 32767),
    secondary=st.integers(-32768, 32767),
    status=st.integers(0, 0xFFFF).map(SlotStatus),
    slot=st.integers(0, 7),
)


@given(
    slots=st.lists(_slot_strategy, max_size=8),
    labels=st.lists(_labels, max_size=8),
    named=st.lists(st.booleans(), min_size=8, max_size=8),
    indicator=st.sampled_from(_SAFE_CHARS),
)
def test_render_rows_fit_and_are_lcd_safe(
    slots: list[SlotReading], labels: list[str], named: list[bool], indicator: str
) -> None:
    entries = [
        NameEntry(s.rom, lbl) for s, lbl, use in zip(slots, labels, named, strict=False) if use
    ]
    rows = render_onewire_rows(slots, entries, indicator)
    present = [s for s in slots if s.status & SlotStatus.PRESENT]
    expected = sum(2 if rom_family(s.rom) == FAMILY_DS2438 else 1 for s in present)
    assert len(rows) == expected
    for row in rows:
        assert len(row) == 20, repr(row)
        assert all(is_lcd_safe(c) for c in row), repr(row)
        assert row[19] == indicator, repr(row)
    for page in paginate(rows):
        assert 1 <= len(page) <= 4
