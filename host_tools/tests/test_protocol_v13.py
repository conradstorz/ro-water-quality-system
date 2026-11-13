"""Protocol 1.3 guards: 1-Wire block 140-199 is additive; v1.2 registers frozen."""

import dataclasses

import pytest

from ro_tools import schema
from ro_tools.generated import registers as reg

# Frozen v1.2 contract subset: name -> (address, type, scale_divisor).
V12_INPUT: dict[str, tuple[int, str, int]] = {
    "protocol_major": (100, "u16", 1),
    "feed_ec_us_cm_x10": (109, "u16", 10),
    "permeate_temp_c_x100": (113, "i16", 100),
    "load_left_raw": (117, "i32", 1),
    "boot_counter": (125, "u32", 1),
    "feed_temp_c_x100": (132, "i16", 100),
    "node_type": (133, "u16", 1),
    "installed_mask": (134, "u16", 1),
}

HEADER = {
    "onewire_device_count": 140,
    "onewire_bus_status": 141,
    "onewire_scan_generation": 142,
    "onewire_age_ms": 143,
}
SLOT_FIELDS = ["rom0", "rom1", "rom2", "rom3", "primary", "secondary", "status"]


def _by_name() -> dict:
    return {r.name: r for r in schema.load().input_registers}


def test_version_and_window():
    m = schema.load()
    assert (m.version_major, m.version_minor) == (1, 3)
    assert (m.input_start, m.input_count) == (100, 100)
    assert reg.PROTOCOL_MINOR == 3
    assert (reg.INPUT_START, reg.INPUT_COUNT) == (100, 100)


def test_v12_registers_unchanged():
    by_name = _by_name()
    for name, (addr, typ, div) in V12_INPUT.items():
        r = by_name[name]
        assert (r.address, r.type, r.scale_divisor, r.access) == (addr, typ, div, "read_only"), name


def test_header_and_slot_addresses():
    by_name = _by_name()
    for name, addr in HEADER.items():
        r = by_name[name]
        assert (r.address, r.type, r.words, r.access) == (addr, "u16", 1, "read_only"), name
    for n in range(8):
        for off, field in enumerate(SLOT_FIELDS):
            name = f"onewire_s{n}_{field}"
            r = by_name[name]
            assert r.address == 144 + 7 * n + off, name
            assert r.words == 1 and r.scale_divisor == 1


def test_slot_signedness():
    by_name = _by_name()
    for n in range(8):
        for field in SLOT_FIELDS:
            expected = "i16" if field in ("primary", "secondary") else "u16"
            assert by_name[f"onewire_s{n}_{field}"].type == expected, (n, field)


def test_reserved_135_139_remain():
    by_name = _by_name()
    for a in range(135, 140):
        r = by_name[f"reserved_{a}"]
        assert (r.address, r.unit) == (a, "reserved")


def test_fault_bit_10():
    assert reg.FaultBits.ONEWIRE_BUS_FAULT == 1 << 10
    assert schema.load().fault_bits[10] == "onewire_bus_fault"


def test_validity_unchanged():
    m = schema.load()
    assert m.critical_validity_bits == (0, 1, 2, 3, 7)
    assert sorted(m.validity_bits) == list(range(11))
    assert not any("onewire" in b.name.lower() for b in reg.ValidityBits)
    assert len(list(reg.ValidityBits)) == 11


def test_roundtrip_nonzero_slots():
    snap = reg.decode_snapshot([0] * reg.INPUT_COUNT)
    values = {
        "onewire_device_count": 8,
        "onewire_bus_status": 0b1000,
        "onewire_scan_generation": 7,
        "onewire_age_ms": 65535,
    }
    for n in range(8):
        values.update(
            {
                f"onewire_s{n}_rom0": 0x2800 + n,
                f"onewire_s{n}_rom1": 0x1111,
                f"onewire_s{n}_rom2": 0x2222,
                f"onewire_s{n}_rom3": 0x3328,
                f"onewire_s{n}_primary": -1234 + n,
                f"onewire_s{n}_secondary": -(n + 1),
                f"onewire_s{n}_status": 0b11 | (n << 2),
            }
        )
    snap = dataclasses.replace(snap, **values)
    words = reg.encode_snapshot(snap)
    assert len(words) == reg.INPUT_COUNT
    assert reg.decode_snapshot(words) == snap
    assert words[144 - 100 + 4] == (-1234) & 0xFFFF
    with pytest.raises(ValueError):
        reg.decode_snapshot([0] * 40)
