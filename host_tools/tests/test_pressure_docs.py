"""RO feed pressure channel (ADR-0010): docs and register map stay consistent."""

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


# Chosen front-end values (ADR-0010) and datasheet limits they must respect.
R_SENSE_OHM = 100
R_LIMIT_OHM = 43
LM317_VREF_MIN_V, LM317_VREF_MAX_V = 1.20, 1.30
ADC_ATTEN3_MAX_MV = 2900  # ESP32-S3 datasheet Table 4-5
GPIO_RAIL_MV = 3300
OVERRANGE_MA = 20.5


def test_front_end_values_are_documented() -> None:
    adr = ADR10.read_text(encoding="utf-8")
    spec = "\n".join(_pressure_section())
    for text in (adr, spec):
        assert "GPIO1" in text and "ADC1_CH0" in text
        assert f"{R_SENSE_OHM} ohm" in text.replace("Ω", "ohm")
        assert f"{R_LIMIT_OHM} ohm" in text.replace("Ω", "ohm")
        assert "TBD" not in text


def test_measuring_range_fits_adc_and_short_reads_as_overrange() -> None:
    assert OVERRANGE_MA * R_SENSE_OHM < ADC_ATTEN3_MAX_MV
    limit_min_ma = LM317_VREF_MIN_V / R_LIMIT_OHM * 1000
    limit_max_ma = LM317_VREF_MAX_V / R_LIMIT_OHM * 1000
    # A shorted transmitter must be distinguishable as overrange ...
    assert limit_min_ma > OVERRANGE_MA
    # ... and must never put more than the 3.3 V rail on the ADC pin.
    assert limit_max_ma * R_SENSE_OHM < GPIO_RAIL_MV
