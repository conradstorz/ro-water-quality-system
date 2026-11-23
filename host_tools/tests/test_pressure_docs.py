"""RO feed pressure channel (ADR-0010): docs and register map stay consistent."""

import re
from pathlib import Path

from ro_tools import schema

REPO = Path(__file__).resolve().parents[2]
ADR10 = REPO / "docs" / "decisions" / "ADR-0010-ro-feed-pressure-4-20ma.md"
HARDWARE_SPEC = REPO / "hardware" / "sensor-node" / "HARDWARE_SPEC.md"

BAR_TO_PSI = 14.5037738
FULL_SCALE_BAR = 16
_U16_MAX = 65535


def _pressure_section() -> list[str]:
    """Return the bullet lines of the ``## Optional pressure channel`` section."""
    out: list[str] = []
    in_section = False
    for line in HARDWARE_SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            in_section = line.startswith("## Optional pressure channel")
            continue
        if in_section and line.startswith("- "):
            out.append(line)
    return out


def test_adr_0010_is_proposed_and_monitoring_only() -> None:
    text = ADR10.read_text(encoding="utf-8")
    assert "**Status:** Proposed" in text
    assert "monitoring only" in text.lower()
    assert "LFT2000" in text and "0-16 bar" in text
    assert "24 V trunk" in text


def test_pressure_validity_bit_is_not_critical() -> None:
    m = schema.load()
    bit = next(b for b, name in m.validity_bits.items() if name == "ro_feed_pressure")
    assert bit not in m.critical_validity_bits


def test_full_scale_fits_pressure_register() -> None:
    m = schema.load()
    reg = next(r for r in m.input_registers if r.name == "ro_feed_pressure_psi_x10")
    assert (reg.type, reg.unit) == ("u16", "psi")
    raw_full_scale = round(FULL_SCALE_BAR * BAR_TO_PSI * reg.scale_divisor)
    assert raw_full_scale == 2321
    assert raw_full_scale <= _U16_MAX


def test_pressure_raw_adc_register_unchanged() -> None:
    m = schema.load()
    reg = next(r for r in m.input_registers if r.name == "pressure_raw_adc")
    assert (reg.address, reg.type, reg.scale_divisor, reg.unit) == (131, "u16", 1, "counts")


def test_pressure_section_found_and_supersedes_250_ohm() -> None:
    lines = _pressure_section()
    assert any("ADR-0010" in ln for ln in lines)
    assert any("Supersedes" in ln and "250 ohm" in ln for ln in lines)
    assert not any("250 ohm" in ln and "Supersedes" not in ln for ln in lines)


def test_unverified_pressure_hardware_values_stay_tbd() -> None:
    """Pin assignment, protection and current limit are not chosen yet (AGENTS.md rule 5)."""
    topics = re.compile(r"series resistor|clamp|current limit|exact assignment", re.IGNORECASE)
    hits = [ln for ln in _pressure_section() if topics.search(ln)]
    assert hits
    for line in hits:
        assert "TBD" in line, line
    protection = next(ln for ln in hits if "series resistor" in ln.lower())
    assert not re.search(r"\d+(?:\.\d+)?\s*k?\s*ohms?\b|[ΩΩ]", protection)
