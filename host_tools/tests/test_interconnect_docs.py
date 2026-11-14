"""The RJ45 trunk pinout YAML is normative; the markdown and sanity rules must agree."""

from pathlib import Path

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
