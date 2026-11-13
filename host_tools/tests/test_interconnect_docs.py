"""The RJ45 trunk pinout YAML is normative; the markdown and sanity rules must agree."""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PINOUT = REPO / "hardware" / "interconnect" / "pinout.yaml"
DOC = REPO / "hardware" / "interconnect" / "NODE_BUS_INTERCONNECT.md"

POWER = {"+24V"}
GROUND = {"GND"}
DATA = {"RS485_A", "RS485_B"}


def load() -> dict:
    return yaml.safe_load(PINOUT.read_text(encoding="utf-8"))


def test_every_rj45_pin_is_assigned_exactly_once():
    pins = load()["pins"]
    assert sorted(pins) == list(range(1, 9))


def test_signals_are_from_the_known_set():
    known = POWER | GROUND | DATA | {"RESERVED"}
    assert set(load()["pins"].values()) <= known


def test_rs485_pair_is_the_center_pair():
    pins = load()["pins"]
    assert {pins[4], pins[5]} == DATA


def test_power_and_ground_are_doubled_and_reserved_pins_are_unconnected():
    pins = load()["pins"]
    values = list(pins.values())
    assert values.count("+24V") == 2 and values.count("GND") == 2
    assert values.count("RESERVED") == 2


def test_power_pins_not_adjacent_to_rs485_pins():
    pins = load()["pins"]
    for pin in (4, 5):
        for neighbour in (pin - 1, pin + 1):
            if neighbour in pins and neighbour not in (4, 5):
                assert pins[neighbour] not in POWER, (pin, neighbour)


def test_doc_table_matches_yaml():
    names = {
        "+24V": "+24V",
        "GND": "GND",
        "RS485_A": "RS485 A",
        "RS485_B": "RS485 B",
        "RESERVED": "Reserved",
    }
    data = load()
    expected: dict[int | str, str] = {pin: names[signal] for pin, signal in data["pins"].items()}
    expected["Shell"] = {"SHIELD": "Shield"}[data["shell"]]
    found: dict[int | str, str] = {}
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        keys = [p.strip() for p in cells[0].split(",")]
        if all(p.isdigit() for p in keys) or keys == ["Shell"]:
            for key in keys:
                k: int | str = int(key) if key.isdigit() else key
                assert k not in found, f"duplicate row for {k}"
                found[k] = cells[1]
    assert found == expected


ADR9 = REPO / "docs" / "decisions" / "ADR-0009-onewire-monitoring-input.md"
HARDWARE = REPO / "hardware"
CONNECTOR_NAME = "Nilight 3-pin waterproof male/female harness connector"


def test_onewire_section_names_connector_and_signals():
    ow = load()["onewire"]
    assert ow["connector"] == CONNECTOR_NAME
    signals = ow["signals"]
    assert set(signals) == {"+5V", "DATA", "GND"}
    for name, entry in signals.items():
        assert entry["cavity"] == "TBD", name


def test_onewire_ratings_and_electrical_values_are_tbd():
    ow = load()["onewire"]
    for key in ("rating_voltage", "rating_current", "polyfuse", "pull_up", "gpio", "max_length"):
        assert ow[key] == "TBD", key
    assert ow["power"] == "node 5V rail, non-parasitic"


def test_interconnect_doc_covers_onewire_and_is_not_rj45():
    text = DOC.read_text(encoding="utf-8")
    assert '"1-WIRE"' in text
    assert "not for the RJ45 RO BUS" in text
    assert "rating_voltage: TBD" in text and "rating_current: TBD" in text


def test_adr_0009_is_proposed_and_monitoring_only():
    text = ADR9.read_text(encoding="utf-8")
    assert "**Status:** Proposed" in text
    assert "monitoring only" in text.lower()
    assert "100-199" in text
    assert "second poll block" in text  # listed as a rejected alternative


HARDWARE_SPEC = HARDWARE / "sensor-node" / "HARDWARE_SPEC.md"
_TOPIC = re.compile(r"gpio|pull[-_ ]?up|series resistor", re.IGNORECASE)
_NUMERIC = re.compile(
    r"\d+(?:\.\d+)?\s*k\d*(?![a-z])"  # 4k7, 4.7k, 4.7 k
    r"|\d+(?:\.\d+)?\s*k?\s*ohms?\b"
    r"|[\u03a9\u2126]"
    r"|\bIO\s?\d+"
    r"|\bGPIO\s?\d+",
    re.IGNORECASE,
)


def _sections(path: Path) -> list[str]:
    """Return the lines of every ``## ...1-Wire...`` section plus ``- 1-Wire`` bullets."""
    out: list[str] = []
    in_section = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            in_section = line.startswith("## ") and "1-wire" in line.lower()
            continue
        if in_section or line.lower().startswith("- 1-wire"):
            out.append(line)
    return out


def _violations(lines: list[str]) -> list[str]:
    bad = []
    for line in lines:
        if _TOPIC.search(line) and ("TBD" not in line or _NUMERIC.search(line)):
            bad.append(line)
    return bad


def test_onewire_sections_are_found() -> None:
    assert any("pull-up" in line.lower() for line in _sections(DOC))
    assert any("series resistor" in line.lower() for line in _sections(HARDWARE_SPEC))


def test_onewire_gpio_pullup_resistor_lines_are_tbd_without_numbers() -> None:
    lines = _sections(DOC) + _sections(HARDWARE_SPEC)
    assert _violations(lines) == []


def test_pinout_onewire_electrical_keys_are_tbd_without_numbers() -> None:
    ow = load()["onewire"]
    for key, value in ow.items():
        if _TOPIC.search(key):
            assert value == "TBD", key
    assert not [v for v in ow.values() if isinstance(v, str) and _NUMERIC.search(v)]


@pytest.mark.parametrize(
    "line",
    [
        "- Pull-up value, GPIO 4, 4.7k pull-up: TBD",
        "- Bus driver: one ESP32 GPIO (TBD), series resistor (4k7), pull-up TBD",
        "- Pull-up 4.7 kohm",
        "- pull-up TBD, 2200 ohm",
        "- GPIO IO5 TBD",
        "- series resistor 330 Ω TBD",
        "- one GPIO, pull-up to 3.3 V",
    ],
)
def test_violation_detector_catches_numbers_and_missing_tbd(line: str) -> None:
    assert _violations([line])
