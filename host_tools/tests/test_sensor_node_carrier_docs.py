"""Sensor-node carrier board (ADR-0012): GPIO map, arithmetic and docs stay consistent."""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
ADR12 = REPO / "docs" / "decisions" / "ADR-0012-sensor-node-carrier.md"
PINOUT = REPO / "hardware" / "sensor-node" / "pinout.yaml"
HARDWARE_SPEC = REPO / "hardware" / "sensor-node" / "HARDWARE_SPEC.md"
INTERCONNECT = REPO / "hardware" / "interconnect" / "NODE_BUS_INTERCONNECT.md"
TODO = REPO / "docs" / "TODO.md"
DATASHEETS = REPO / "hardware" / "sensor-node" / "datasheets"

# Cited pin facts (WROOM-1 datasheet v1.2 Tables 3-4, S3 datasheet Table 2-14, DevKitC-1 user guide v1.1).
STRAPPING = {0, 3, 45, 46}
USB = {19, 20}
JTAG = {39, 40, 41, 42}
UART0 = {43, 44}
OCTAL_PSRAM = {35, 36, 37}
BOARD_RGB_LED = {38, 48}  # GPIO not marked on the clone; the DevKitC candidates
NOT_ON_MODULE = set(range(22, 35))
ADC1 = set(range(1, 11))
PCNT_UNITS = 4  # S3 TRM v1.2 chapter 38
DEVKITC_HEADERS = {4, 5, 6, 7, 15, 16, 17, 18, 8, 3, 46, 9, 10, 11, 12, 13, 14}  # J1
DEVKITC_HEADERS |= {43, 44, 1, 2, 42, 41, 40, 39, 38, 37, 36, 35, 0, 45, 48, 47, 21, 20, 19}  # J3
HIGH_GLITCH_AT_POWER_UP = {18}  # S3 datasheet Table 2-2
GLITCH_AT_POWER_UP = set(range(1, 19))  # GPIO1-18 (15/16 as XTAL_32K_P/N), Table 2-2
PUSH_PULL_DRIVEN = {
    "HX711_A_DOUT",
    "HX711_B_DOUT",
    "PULSE_PERMEATE",
    "PULSE_CONCENTRATE",
    "RS485_RX",
}


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (two signals on one GPIO)."""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise ValueError(f"duplicate keys {duplicates}")
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load() -> dict:
    return yaml.load(PINOUT.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)


def gpio() -> dict[int, dict]:
    return load()["gpio"]


# ---------------------------------------------------------------- GPIO map


def test_excluded_sets_match_cited_facts() -> None:
    ex = load()["excluded"]
    assert set(ex["strapping"]) == STRAPPING
    assert set(ex["usb"]) == USB
    assert set(ex["jtag"]) == JTAG
    assert set(ex["uart0_console"]) == UART0
    assert set(ex["octal_psram"]) == OCTAL_PSRAM
    assert set(ex["board_rgb_led"]) == BOARD_RGB_LED
    assert set(ex["not_on_module"]) == NOT_ON_MODULE
    assert set(load()["adc1_gpios"]) == ADC1
    assert load()["pcnt_units"] == PCNT_UNITS


def test_pins_and_signals_are_unique_and_none_is_excluded() -> None:
    pins = gpio()
    signals = [entry["signal"] for entry in pins.values()]
    assert len(signals) == len(set(signals))
    forbidden = STRAPPING | USB | JTAG | UART0 | OCTAL_PSRAM | BOARD_RGB_LED | NOT_ON_MODULE
    assert not set(pins) & forbidden
    assert set(pins) <= DEVKITC_HEADERS


def test_duplicate_gpio_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        yaml.load("gpio:\n  1: a\n  1: b\n", Loader=_UniqueKeyLoader)


def test_gpio1_is_pressure_and_analog_only_on_adc1() -> None:
    pins = gpio()
    assert pins[1]["signal"] == "PRESSURE_ADC"
    analog = {p for p, e in pins.items() if e["kind"] == "analog"}
    assert 1 in analog and analog <= ADC1


def test_two_button_pins_reserved() -> None:
    buttons = {e["signal"]: p for p, e in gpio().items() if e["kind"] == "button"}
    assert set(buttons) == {"BTN_NEXT", "BTN_HOLD"}


def test_pcnt_count_respected() -> None:
    pulses = [p for p, e in gpio().items() if e["kind"] == "pcnt"]
    assert len(pulses) == 2 <= PCNT_UNITS


def test_required_functions_present() -> None:
    kinds = [e["kind"] for e in gpio().values()]
    assert kinds.count("rs485") == 3
    assert kinds.count("i2c") == 2
    assert kinds.count("hx711") == 4
    assert kinds.count("dip") == 4
    assert "onewire" not in kinds  # DS2482-100 on I2C, no GPIO


def test_outputs_that_matter_at_boot_avoid_high_glitch_pins() -> None:
    pins = gpio()
    for p, e in pins.items():
        if e["signal"] in {"RS485_DE_RE", "RS485_TX", "HX711_A_SCK", "HX711_B_SCK"}:
            assert p not in HIGH_GLITCH_AT_POWER_UP, e["signal"]


def test_push_pull_driven_glitch_pins_have_series_resistor() -> None:
    for p, e in gpio().items():
        if e["signal"] in PUSH_PULL_DRIVEN and p in GLITCH_AT_POWER_UP:
            assert e.get("series_ohm", 0) >= 1000, e["signal"]
            assert 3.3 / e["series_ohm"] * 1000 <= 3.3  # contention current, mA


def test_i2c_addresses_are_unique() -> None:
    addr = load()["i2c_addresses"]
    fixed = [v for v in addr.values() if isinstance(v, int)]
    assert sorted(fixed) == [0x18, 0x48, 0x49]
    lcd_ranges = set(range(0x20, 0x28)) | set(range(0x38, 0x40))
    assert not set(fixed) & lcd_ranges


def test_adr_gpio_table_matches_yaml() -> None:
    found: dict[int, str] = {}
    for line in ADR12.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[0].isdigit():
            found[int(cells[0])] = cells[1]
    assert found == {p: e["signal"] for p, e in gpio().items()}


# ---------------------------------------------------------------- current budget and fuse


def _budget() -> list[tuple[str, str, float]]:
    rows = []
    for line in ADR12.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4 and cells[1] in {"3V3", "5V", "24V"}:
            rows.append((cells[0], cells[1], float(cells[2])))
    return rows


def _total(rail: str) -> float:
    return next(v for name, r, v in _budget() if r == rail and name.startswith("**"))


def test_budget_rows_sum_to_totals() -> None:
    for rail in ("3V3", "5V", "24V"):
        parts = [v for name, r, v in _budget() if r == rail and not name.startswith("**")]
        assert sum(parts) == pytest.approx(_total(rail), abs=0.5), rail


# AMS1117 datasheet: the reference for the board's unknown-maker 1117-3.3.
AMS1117_MAX_MA = 1000  # General Description: up to 1 A output current
AMS1117_LIMIT_MIN_MA = 900  # Electrical Characteristics: current limit min
AMS1117_DROPOUT_SPEC_MA = 800  # Note 4: dropout specified up to 0.8 A
AMS1117_DROPOUT_MAX_V = 1.3  # Electrical Characteristics: dropout max at 0.8 A
AMS1117_IQ_MAX_MA = 11  # Electrical Characteristics: quiescent current max
AMS1117_MIN_LOAD_MA = 10  # Note 5: minimum load current
AMS1117_VOUT_MAX_V = 3.399  # AMS1117-3.3 output, full temperature range
AMS1117_THETA_JA = 90  # SOT-223, Absolute Maximum Ratings
AMS1117_TJ_MAX = 125  # Application Hints
WROOM_SUPPLY_MIN_MA = 500  # WROOM-1 Table 10: external supply must deliver >= 0.5 A
DS18B20_VIH_MIN = 2.2
DATA_HIGH_V = 3.3

# LMR36015 setpoint: RFBT 100 kohm / RFBB 23.2 kohm, both 0.1 %; VFB 0.985-1.015 V.
RFBT, RFBB, R_TOL = 100.0, 23.2, 0.001
VFB_MIN, VFB_MAX = 0.985, 1.015
BUCK_MIN = VFB_MIN * (1 + RFBT * (1 - R_TOL) / (RFBB * (1 + R_TOL)))
BUCK_MAX = VFB_MAX * (1 + RFBT * (1 + R_TOL) / (RFBB * (1 - R_TOL)))
SL_VF_MAX = 0.45  # 1N5819HW (marking SL) VF max at 1 A, DS30217
D2_OLD_VF_MAX = 0.45  # the replaced 1N5819HW D2
LM66100_RON_MAX = 0.110  # SLVSEZ8A, VIN = 5 V, -40 to 125 C
FIVE_V_LOAD_MAX = 5.5  # HX711 VSUP, DS18B20 VDD, PCA9306 VREF2, TPD1E10B06 VRWM, LM66100 VIN
AMBIENT_C = 50


def test_5v_rail_carries_the_3v3_total_and_fits_the_regulators() -> None:
    board = next(v for name, r, v in _budget() if r == "5V" and name.startswith("Board 5Vin pin"))
    assert board == pytest.approx(_total("3V3") + AMS1117_IQ_MAX_MA)
    assert _total("3V3") <= AMS1117_DROPOUT_SPEC_MA <= AMS1117_LIMIT_MIN_MA <= AMS1117_MAX_MA
    assert AMS1117_MAX_MA >= WROOM_SUPPLY_MIN_MA
    assert _total("5V") <= 1500  # LMR36015 output current


def test_buck_setpoint_band_and_5v_load_limits() -> None:
    assert BUCK_MIN == pytest.approx(5.222, abs=0.001)
    assert BUCK_MAX == pytest.approx(5.399, abs=0.001)
    assert BUCK_MAX <= FIVE_V_LOAD_MAX
    text = ADR12.read_text(encoding="utf-8")
    assert "5.22-5.40 V" in text
    assert "23.2 kΩ 0.1 %" in text
    # With 1 % feedback resistors the headroom would shrink below 0.1 V: hence 0.1 %.
    one_pct_min = VFB_MIN * (1 + RFBT * 0.99 / (RFBB * 1.01))
    i_in = (_total("3V3") + AMS1117_IQ_MAX_MA) / 1000
    assert one_pct_min - i_in * LM66100_RON_MAX - SL_VF_MAX < 3.3 + AMS1117_DROPOUT_MAX_V + 0.1


def test_1117_dropout_headroom() -> None:
    i_in = (_total("3V3") + AMS1117_IQ_MAX_MA) / 1000
    need = 3.3 + AMS1117_DROPOUT_MAX_V
    old_buck_min = VFB_MIN * (1 + 100 / 24.9)
    # Original design: buck 5.0 V, 1N5819HW D2, worst-case on-board SL diode. Fails.
    old = old_buck_min - D2_OLD_VF_MAX - SL_VF_MAX
    assert old == pytest.approx(4.04, abs=0.01)
    assert old < need
    # LM66100 alone with the buck at 5.0 V still fails.
    assert old_buck_min - i_in * LM66100_RON_MAX - SL_VF_MAX < need
    # Chosen: LM66100 and the buck at 5.22-5.40 V.
    ldo_in = BUCK_MIN - i_in * LM66100_RON_MAX - SL_VF_MAX
    assert ldo_in == pytest.approx(4.718, abs=0.001)
    assert ldo_in - need >= 0.1
    assert ldo_in > AMS1117_VOUT_MAX_V + AMS1117_DROPOUT_MAX_V  # recorded residual, 19 mV
    text = ADR12.read_text(encoding="utf-8")
    assert "4.718 V ≥ 4.60 V" in text
    assert "**118 mV**" in text


BUCK_V, ETA, D1_VF = 5.40, 0.85, 0.79  # buck maximum output, used for power


def test_buck_input_row_is_arithmetic() -> None:
    buck = next(v for name, r, v in _budget() if r == "24V" and name.startswith("Buck input"))
    expected = BUCK_V * _total("5V") / ETA / (24 - D1_VF)
    assert buck == pytest.approx(expected, abs=0.2)
    assert ETA < 0.90  # below the cited 90 % point (24 VIN, 5 VOUT, 1 A)


MF_R065_HOLD_A = {23: 0.65, 50: 0.47, 60: 0.41}  # Bourns MF-R Rev. AR derating table
FUSE_MARGIN = 1.25


def test_fuse_above_budget_with_margin() -> None:
    budget_a = _total("24V") / 1000
    assert MF_R065_HOLD_A[50] >= FUSE_MARGIN * budget_a
    assert MF_R065_HOLD_A[60] >= budget_a
    low_input = BUCK_V * _total("5V") / 1000 / ETA / (18 - D1_VF) + (30.2 + 50.0) / 1000
    assert MF_R065_HOLD_A[50] > low_input
    assert "MF-R065" in ADR12.read_text(encoding="utf-8")


def test_tvs_clamp_below_buck_abs_max() -> None:
    smbj33a_vc, lmr36015_vin_max = 53.3, 66
    assert smbj33a_vc < lmr36015_vin_max


def test_ldo_thermal_numbers() -> None:
    assert round(BUCK_MAX, 2) == BUCK_V
    text = ADR12.read_text(encoding="utf-8")
    i_cont = (_total("3V3") - 355.0 + 107.9) / 1000
    p_off = (BUCK_V - 3.3) * i_cont
    assert f"{p_off:.3f} W" in text
    assert f"{p_off * AMS1117_THETA_JA:.1f} °C" in text
    assert AMBIENT_C + p_off * AMS1117_THETA_JA < AMS1117_TJ_MAX  # Wi-Fi off fits
    p_tx = (BUCK_V - 3.3) * _total("3V3") / 1000
    assert f"{p_tx:.3f} W" in text
    assert f"{p_tx * AMS1117_THETA_JA:.1f} °C" in text
    assert AMBIENT_C + p_tx * AMS1117_THETA_JA > AMS1117_TJ_MAX  # hence the Wi-Fi rule
    i_max = (AMS1117_TJ_MAX - AMBIENT_C) / AMS1117_THETA_JA / (BUCK_V - 3.3) * 1000
    assert f"{i_max:.0f} mA" in text


# ---------------------------------------------------------------- front-end arithmetic

ADS_VDD = 3.3
ADS_ABS_MARGIN = 0.3
ADS_INPUT_MAX_MA = 10
BAT54S_VF_10MA = 0.40


def test_ec_divider_keeps_ads_input_in_range() -> None:
    ratio = 10 / (10 + 10)
    assert 5.5 * ratio <= ADS_VDD  # in range, clamp idle
    clamp_v = ADS_VDD + BAT54S_VF_10MA
    assert clamp_v <= ADS_VDD + ADS_ABS_MARGIN + 0.1  # clamp, then 1 kohm, then AIN
    fault_ma = (24 - clamp_v) / 10
    assert fault_ma < ADS_INPUT_MAX_MA


def test_pressure_divider_unchanged_in_range() -> None:
    assert 20.5 * 100 < 2900  # ADR-0010, S3 datasheet Table 4-5


VT_POS_MAX_3V3 = 2.0 + 0.3 / 1.5 * (3.1 - 2.0)  # SN74LVC2G17, interpolated 3.0 -> 4.5 V
VT_NEG_MIN = 0.8
LVC_VI_MAX = 5.5


def test_pulse_divider_window() -> None:
    ratio = 22 / (10 + 22)
    assert VT_POS_MAX_3V3 == pytest.approx(2.22)
    assert 5.0 * ratio > VT_POS_MAX_3V3  # 5 V push-pull reads high
    assert BUCK_MIN * 22 / (4.7 + 10 + 22) > VT_POS_MAX_3V3  # open collector, 5 V rail minimum
    assert BUCK_MAX * 22 / (4.7 + 10 + 22) < 3.3  # clamp idle at the 5 V rail maximum
    assert 1.16 * ratio <= VT_NEG_MIN  # documented maximum low level
    clamp_v = 3.3 + BAT54S_VF_10MA
    assert clamp_v < LVC_VI_MAX  # 24 V input is clamped below VI max
    clamp_ma = (24 - clamp_v) / 10 - clamp_v / 22
    assert clamp_ma == pytest.approx(1.86, abs=0.01)
    assert clamp_ma < 200  # BAT54S IO


RWPU_MIN_OHM = 1000
DS2482_VOL1_LOAD_MA = 4.0
DS2482_PIN_MAX_MA = 20
DS18B20_SINK_MA = 4.0
DS18B20_VIL_MAX = 0.8
DS2482_VIL1_MAX_3V3 = 0.9
SERIES_OHM = 33


def test_onewire_pullup_current_within_driver_limits() -> None:
    i_ma = 3.3 / RWPU_MIN_OHM * 1000
    assert i_ma <= DS2482_VOL1_LOAD_MA
    assert i_ma <= DS18B20_SINK_MA
    assert i_ma < DS2482_PIN_MAX_MA
    low = 0.4 + i_ma / 1000 * SERIES_OHM
    assert low < DS18B20_VIL_MAX and low < DS2482_VIL1_MAX_3V3
    assert DATA_HIGH_V >= DS18B20_VIH_MIN  # 3.3 V DATA works with 5 V device power


FIELD_FAULT_V = 24.0
RREF_MIN_KOHM = 3.3
PRESSURE_CLAMP_MA = 2.0  # ADR-0010
R_BLEED_OHM = 120


def test_bleeder_sinks_worst_case_fault_injection() -> None:
    clamp_v = 3.3 + BAT54S_VF_10MA
    pulse = 2 * ((FIELD_FAULT_V - clamp_v) / 10 - clamp_v / 22)
    ec = 2 * (FIELD_FAULT_V - clamp_v) / 10
    thermistor_clamp = 2 * (FIELD_FAULT_V - clamp_v) / 10
    rref = 2 * (FIELD_FAULT_V - 3.3) / RREF_MIN_KOHM
    total = pulse + ec + thermistor_clamp + rref + PRESSURE_CLAMP_MA
    assert total == pytest.approx(26.39, abs=0.01)
    bleed_ma = 3.3 / R_BLEED_OHM * 1000
    assert bleed_ma >= total
    assert 3.3**2 / R_BLEED_OHM <= 0.25
    bleed_row = next(v for name, r, v in _budget() if name.startswith("3V3 bleeder"))
    assert bleed_row == pytest.approx(bleed_ma, abs=0.05)
    assert bleed_ma >= AMS1117_MIN_LOAD_MA  # also the 1117 minimum load (AMS1117 Note 5)


def test_rs485_bias_and_termination_arithmetic() -> None:
    term = 120 * 120 / (120 + 120)
    assert 3.3 * term / (2 * 390 + term) >= 0.2
    assert 5.0 * term / (2 * 680 + term) >= 0.2
    assert 3.3**2 / 120 <= 0.25


def test_hx711_avdd_below_vsup() -> None:
    avdd = 1.25 * (20 + 8.2) / 8.2
    assert avdd == pytest.approx(4.30, abs=0.01)
    assert avdd <= BUCK_MIN - 0.1


def test_button_rc() -> None:
    tau_ms = 10e3 * 100e-9 * 1000
    assert tau_ms == pytest.approx(1.0)
    assert 3.3 * 100 / (10e3 + 100) < 0.25 * 3.3  # pressed level below VIL


# ---------------------------------------------------------------- documents


def test_adr_is_proposed_and_monitoring_only() -> None:
    text = ADR12.read_text(encoding="utf-8")
    assert "**Status:** Proposed" in text
    assert "monitoring hardware" in text
    for part in (
        "ESP32-S3 2025-V1.4",
        "DevKitC-1-N16R8",
        "LMR36015",
        "AMS1117",
        "LM66100",
        "THVD1450",
        "SM712",
        "SMBJ33A",
        "MBRS3100",
        "DS2482S-100+",
        "ADS1115",
        "PCA9306",
        "SN74LVC2G17",
        "TPD1E10B06",
        "MF-R010",
        "EOL",
    ):
        assert part in text, part


def test_adr_has_no_tbd_in_closed_sections() -> None:
    section = ""
    bad = []
    for line in ADR12.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line
            continue
        closed = re.match(r"## [1-8]\.", section) is not None
        if closed and "TBD" in line and "cavit" not in line.lower():
            bad.append(line)
    assert bad == []


def test_cited_datasheets_are_in_repo() -> None:
    names = " ".join(p.name for p in DATASHEETS.glob("*.pdf"))
    for key in ("THVD1450", "LMR36015", "ADS1115", "PCA9306", "DS2482", "HX711", "MF-R", "AMS1117", "LM66100"):
        assert key in names, key


def test_interconnect_doc_rom_notation_and_budget() -> None:
    text = INTERCONNECT.read_text(encoding="utf-8")
    assert "CRC byte first" not in text
    assert "family byte first and CRC byte last" in text
    assert "ASSUMPTION" not in text
    assert "305.6 mA" in text


def test_board_photos_are_in_repo_and_cited() -> None:
    reference = REPO / "hardware" / "sensor-node" / "reference"
    text = ADR12.read_text(encoding="utf-8")
    for view in ("top", "bottom", "ldo-1117-closeup", "sl-diodes-closeup"):
        name = f"esp32-s3-n16r8-board-v1.4-{view}.jpg"
        assert (reference / name).is_file(), name
        assert name in text, name


def test_board_bench_items_listed() -> None:
    bench = ADR12.read_text(encoding="utf-8").split("- **Bench (Stage D):**")[1]
    for item in (
        "RGB LED GPIO",
        "5Vin passes through an SL diode",
        "orientation of each SL diode",
        "IN-OUT and USB-OTG jumper state",
        "1117 temperature",
        "actual dropout",
        "esptool chip_id",
        "esptool flash_id",
    ):
        assert item in bench, item


def test_hardware_spec_names_adr_and_no_5v_excitation() -> None:
    text = HARDWARE_SPEC.read_text(encoding="utf-8")
    assert "ADR-0012" in text
    assert "5V excitation" not in text
    assert "exact board TBD" not in text


def test_todo_design_boxes_ticked() -> None:
    text = TODO.read_text(encoding="utf-8")
    block = text[text.index("### Claude to design") : text.index("### Bench measurements")]
    boxes = [ln for ln in block.splitlines() if ln.startswith("- [")]
    assert len(boxes) == 8
    assert all(ln.startswith("- [x]") for ln in boxes)
