"""Fixed LCD texts in the exception-driven LCD spec fit columns 1-19 (column 20 is reserved)."""

import re
from pathlib import Path

import pytest

from ro_tools import schema
from ro_tools.onewire_names import is_lcd_safe

REPO = Path(__file__).resolve().parents[2]
SPEC = REPO / "docs" / "specs" / "EXCEPTION_DRIVEN_LCD_AND_FAULTS_SPEC.md"
CONTENT_COLS = 19
RO_PREFIX = "RO: "


def _text() -> str:
    return SPEC.read_text(encoding="utf-8")


def _state_table() -> dict[int, tuple[str, str]]:
    rows = re.findall(r"^\s*\| (\d+) \| `([a-z_]+)` \| `([^`]+)` \|$", _text(), re.MULTILINE)
    return {int(v): (name, lcd) for v, name, lcd in rows}


def test_state_table_covers_every_ro_state() -> None:
    enum = schema.load().enums["ro_state"]
    table = _state_table()
    assert {v: name for v, (name, _) in table.items()} == {int(k): v for k, v in enum.items()}


def test_state_texts_fit_and_are_lcd_safe() -> None:
    for _, lcd in _state_table().values():
        row = RO_PREFIX + lcd
        assert len(row) <= CONTENT_COLS, row
        assert all(is_lcd_safe(c) for c in row), row


def _header(severity: str, n: int, m: int) -> str:
    def cap(x: int) -> str:
        return "99+" if x > 99 else str(x)

    return f"{severity}{f'{cap(n)}/{cap(m)}':>{CONTENT_COLS - len(severity)}}"


@pytest.mark.parametrize("severity", ["!! CRITICAL", "! WARNING"])
@pytest.mark.parametrize(("n", "m"), [(1, 2), (10, 12), (99, 99), (100, 250)])
def test_fault_header_fits(severity: str, n: int, m: int) -> None:
    row = _header(severity, n, m)
    assert len(row) == CONTENT_COLS, repr(row)
    assert row[len(severity)] == " ", repr(row)


def test_documented_examples_match_rule() -> None:
    text = _text()
    for example in (
        _header("!! CRITICAL", 1, 2),
        _header("!! CRITICAL", 10, 12),
        _header("! WARNING", 1, 3),
    ):
        assert f"`{example}`" in text, example


@pytest.mark.parametrize("fixed", ["STARTING: DATA WAIT", "CTRL STATUS UNKNOWN"])
def test_fixed_texts_fit(fixed: str) -> None:
    assert len(fixed) <= CONTENT_COLS
    assert f"`{fixed}`" in _text()


def test_no_overlong_backticked_rows_remain() -> None:
    for old in ("STARTING / DATA WAIT", "RO STATE:", "!! CRITICAL  1/2 !!"):
        assert old not in _text(), old
