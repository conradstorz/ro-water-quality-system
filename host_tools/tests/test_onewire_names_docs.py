"""1-Wire device names (ADR-0011): docs, register map and reference renderer stay consistent."""

import dataclasses
import re
from pathlib import Path

from ro_tools import schema
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    SlotReading,
    SlotStatus,
    make_rom,
    parse_rom,
)
from ro_tools.onewire_names import (
    LABEL_MAX_CHARS,
    NameEntry,
    encode_name_table,
    render_onewire_rows,
    unnamed_label,
)

REPO = Path(__file__).resolve().parents[2]
ADR11 = REPO / "docs" / "decisions" / "ADR-0011-onewire-device-names.md"
NAME_TABLE_DOC = REPO / "protocol" / "ONEWIRE_NAME_TABLE.md"
LCD_SPEC = REPO / "docs" / "specs" / "SENSOR_NODE_LCD_SPEC.md"
FAULT_SPEC = REPO / "docs" / "specs" / "EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md"
LCD_TESTS = REPO / "docs" / "test" / "LCD_FAULT_PRIORITY_TESTS.md"
ACCEPTANCE = REPO / "docs" / "test" / "ACCEPTANCE_TEST_PLAN.md"
AGENTS = REPO / "AGENTS.md"

#: Example ROM used throughout the docs (also in config/onewire_bindings.yaml).
EXAMPLE_ROM_TEXT = "28FF1B2C3D5F4EDE"
_ROM_TOKEN = re.compile(r"\b[0-9A-F]{16}\b")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("|") and not set(line) <= set("|-: "):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def test_name_table_doc_matches_yaml() -> None:
    m = schema.load()
    doc = {int(r[0]): r[1] for r in _table_rows(_read(NAME_TABLE_DOC)) if r[0].isdigit()}
    block = range(m.names_start, m.names_start + m.names_count)
    yaml_names = {r.address: r.name for r in m.holding_registers if r.address in block}
    assert len(yaml_names) == m.names_count == 83
    assert doc == yaml_names


def test_name_table_doc_states_limits() -> None:
    m = schema.load()
    text = _read(NAME_TABLE_DOC)
    assert m.names_label_max_chars == LABEL_MAX_CHARS == 11
    assert f"label_max_chars: {m.names_label_max_chars}" in text
    assert f"1–{m.names_label_max_chars} characters" in text
    assert f"`names_entry_count` > {m.names_entry_count_max}" in text
    assert "all-zero ROM" in text
    assert "keeps the previous table" in text
    assert "ILLEGAL_DATA_ADDRESS" in text
    label5 = [r for r in _table_rows(text) if r[1].endswith("_label5")]
    assert len(label5) == m.names_entry_count_max
    assert all("low byte must be NUL" in r[2] for r in label5)


def test_name_table_doc_example_words() -> None:
    rom = parse_rom(EXAMPLE_ROM_TEXT)
    words = encode_name_table([NameEntry(rom, "x")], revision=0)[3:7]
    text = _read(NAME_TABLE_DOC)
    assert f"0x{rom:016X}" in text
    assert ", ".join(f"0x{w:04X}" for w in words) in text


def test_adr_0011_is_proposed_and_display_only() -> None:
    text = _read(ADR11)
    assert "**Status:** Proposed" in text
    assert "display-only" in text and "monitoring only" in text
    assert "240-322" in text and "FC16" in text
    assert "option A" in text and "column 20" in text.lower()
    assert "1-11" in text
    for alternative in ("Per-value entries", "NVS", "input block"):
        assert alternative in text
    assert "no-writable-calibration" in text
    assert "**Deferred:**" in text


def test_doc_roms_are_crc_valid() -> None:
    for path in (ADR11, NAME_TABLE_DOC, LCD_SPEC, FAULT_SPEC, LCD_TESTS, ACCEPTANCE):
        for token in _ROM_TOKEN.findall(_read(path)):
            assert parse_rom(token) != 0, (path.name, token)


def test_unnamed_example_matches_code() -> None:
    label = unnamed_label(parse_rom(EXAMPLE_ROM_TEXT))
    assert label == "?28-1BFF"
    for path in (LCD_SPEC, LCD_TESTS):
        assert label in _read(path), path.name


def test_lcd_spec_example_page_is_rendered_by_code() -> None:
    pv = SlotStatus.PRESENT | SlotStatus.VALID
    ds18 = parse_rom(EXAMPLE_ROM_TEXT)
    ds24 = make_rom(FAMILY_DS2438, 0xA1B2C3D4)
    unnamed = make_rom(FAMILY_DS18B20, 0xBEEF)
    stale = make_rom(FAMILY_DS18B20, 0x7A31)
    slots = [
        SlotReading(slot=0, rom=ds24, primary=2210, secondary=3300, status=pv),
        SlotReading(slot=0, rom=ds18, primary=2150, secondary=0, status=pv),
        SlotReading(slot=0, rom=unnamed, primary=-1230, secondary=0, status=pv),
        SlotReading(slot=0, rom=stale, primary=0, secondary=0, status=pv | SlotStatus.STALE),
    ]
    slots = [
        dataclasses.replace(s, slot=i) for i, s in enumerate(sorted(slots, key=lambda s: s.rom))
    ]
    entries = [NameEntry(ds18, "Outside air"), NameEntry(ds24, "Tank air")]
    rows = render_onewire_rows(slots, entries)
    assert len(rows) == 5
    text = _read(LCD_SPEC)
    for row in rows:
        assert f"[{row}]" in text, row


def test_column_20_rule_in_both_lcd_specs() -> None:
    for path in (LCD_SPEC, FAULT_SPEC):
        text = _read(path)
        assert "Column 20" in text or "column 20" in text, path.name
        assert "columns 1-19" in text, path.name
        assert "after diagnostics" in text or "after the diagnostics page" in text, path.name
        assert "never preempt" in text, path.name
        assert "A00" in text, path.name


def test_lcd_fault_tests_and_acceptance_cover_names() -> None:
    lcd = _read(LCD_TESTS)
    assert "never preempt" in lcd
    assert "identical to the same faults without names" in lcd
    acceptance = _read(ACCEPTANCE)
    assert "prior table" in acceptance
    assert "re-pushes" in acceptance
    assert "protocol 1.3 node" in acceptance and "production_permitted" in acceptance


def test_agents_names_table_display_only() -> None:
    text = _read(AGENTS)
    assert any(
        "name table" in ln and "display-only" in ln and "actuator command" in ln
        for ln in text.splitlines()
    )
