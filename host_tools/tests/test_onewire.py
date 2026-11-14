"""Tests for the 1-Wire ROM/slot model and RegisterBank.set_onewire."""

from __future__ import annotations

import struct

import pytest

from ro_tools.generated.registers import SNAPSHOT_LAYOUT, Snapshot, encode_snapshot
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    SLOT_COUNT,
    BusStatus,
    OneWireDevice,
    SlotReading,
    SlotStatus,
    dallas_crc8,
    decode_slots,
    encode_onewire,
    make_rom,
    rom_crc_ok,
    rom_family,
)
from ro_tools.sim.register_bank import RegisterBank


def _snap(fields: dict[str, int]) -> Snapshot:
    return Snapshot(**fields)


def test_crc8_known_vector() -> None:
    assert dallas_crc8(bytes([0x02, 0x1C, 0xB8, 0x01, 0x00, 0x00, 0x00])) == 0xA2


def test_rom_round_trip_and_bit_flip() -> None:
    rom = make_rom(FAMILY_DS18B20, 0x0123456789AB)
    assert rom_family(rom) == FAMILY_DS18B20
    assert (rom >> 8) & 0xFFFFFFFFFFFF == 0x0123456789AB
    assert rom_crc_ok(rom)
    assert (rom >> 56) == dallas_crc8(rom.to_bytes(8, "little")[:7])
    for bit in (0, 9, 30, 55, 56, 63):
        assert not rom_crc_ok(rom ^ (1 << bit))


def test_round_trip_two_devices() -> None:
    a = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=2150)
    b = OneWireDevice(make_rom(FAMILY_DS2438, 2), primary=2210, secondary=3300)
    snap = _snap(encode_onewire([a, b], age_ms=120, generation=7))
    assert snap.onewire_device_count == 2
    assert snap.onewire_age_ms == 120
    assert snap.onewire_scan_generation == 7
    slots = decode_slots(snap)
    assert len(slots) == 2
    assert all(s.usable for s in slots)
    by_rom = {s.rom: s for s in slots}
    assert by_rom[a.rom].primary == 2150
    assert by_rom[b.rom].primary == 2210
    assert by_rom[b.rom].secondary == 3300


def test_sorted_by_rom() -> None:
    devs = [OneWireDevice(make_rom(FAMILY_DS18B20, s), primary=s) for s in (5, 1, 3)]
    slots = decode_slots(_snap(encode_onewire(devs)))
    roms = [s.rom for s in slots]
    assert roms == sorted(roms)
    assert roms == sorted(d.rom for d in devs)


def test_overflow_keeps_lowest() -> None:
    devs = [OneWireDevice(make_rom(FAMILY_DS18B20, s), primary=1) for s in range(9)]
    snap = _snap(encode_onewire(devs))
    assert snap.onewire_bus_status & BusStatus.OVERFLOW
    slots = decode_slots(snap)
    assert len(slots) == SLOT_COUNT == 8
    assert [s.rom for s in slots] == sorted(d.rom for d in devs)[:8]


def test_unsupported_family() -> None:
    dev = OneWireDevice(make_rom(0x01, 9), primary=500, secondary=7)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.status & SlotStatus.UNSUPPORTED_FAMILY
    assert slot.status & SlotStatus.PRESENT
    assert not slot.status & SlotStatus.VALID
    assert slot.primary == 0 and slot.secondary == 0
    assert slot.rom == dev.rom
    assert not slot.usable


def test_crc_error_device() -> None:
    dev = OneWireDevice(make_rom(FAMILY_DS18B20, 4), primary=2000, crc_error=True)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.status & SlotStatus.CRC_ERROR
    assert not slot.status & SlotStatus.VALID
    assert slot.primary == 0
    assert not slot.usable


def test_missing_device() -> None:
    ok = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=2000)
    gone = OneWireDevice(make_rom(FAMILY_DS18B20, 2), primary=2000, present=False, missing=True)
    snap = _snap(encode_onewire([ok, gone]))
    assert snap.onewire_device_count == 1
    slots = {s.rom: s for s in decode_slots(snap)}
    s = slots[gone.rom]
    assert s.status & SlotStatus.MISSING
    assert not s.status & SlotStatus.PRESENT
    assert not s.status & SlotStatus.VALID
    assert not s.usable


def test_stale_not_usable() -> None:
    dev = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=2000, stale=True)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.status & SlotStatus.STALE
    assert not slot.usable


@pytest.mark.parametrize("present,missing", [(False, False), (True, True)])
def test_present_missing_combo_rejected(present: bool, missing: bool) -> None:
    with pytest.raises(ValueError):
        OneWireDevice(make_rom(FAMILY_DS18B20, 1), present=present, missing=missing)


def test_invalid_device_values_zeroed() -> None:
    dev = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=2000, secondary=5, valid=False)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.primary == 0 and slot.secondary == 0
    assert not slot.status & SlotStatus.VALID
    assert not slot.usable


def test_negative_age_rejected() -> None:
    with pytest.raises(ValueError):
        encode_onewire([], age_ms=-1)


@pytest.mark.parametrize("rom", [-1, 1 << 64])
def test_rom_out_of_range_rejected(rom: int) -> None:
    with pytest.raises(ValueError):
        OneWireDevice(rom)


def test_bus_status_passed_through() -> None:
    status = BusStatus.BUS_SHORT | BusStatus.CRC_ERRORS
    assert encode_onewire([], bus_status=status)["onewire_bus_status"] == int(status)


def test_stale_with_crc_error_unusable() -> None:
    dev = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=2000, stale=True, crc_error=True)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.status & SlotStatus.STALE and slot.status & SlotStatus.CRC_ERROR
    assert not slot.usable


def test_age_saturates() -> None:
    assert encode_onewire([], age_ms=70000)["onewire_age_ms"] == 65535


def test_empty_all_zero() -> None:
    fields = encode_onewire([])
    assert len(fields) == 60
    assert all(v == 0 for v in fields.values())
    assert decode_slots(_snap(fields)) == ()


def test_duplicate_rom_raises() -> None:
    rom = make_rom(FAMILY_DS18B20, 1)
    with pytest.raises(ValueError):
        encode_onewire([OneWireDevice(rom), OneWireDevice(rom)])


def test_field_names_exist_in_layout() -> None:
    names = {n for n, _, _ in SNAPSHOT_LAYOUT}
    devs = [OneWireDevice(make_rom(FAMILY_DS18B20, s), primary=-5) for s in range(8)]
    assert set(encode_onewire(devs)) <= names


def test_negative_primary_encoded_as_i16() -> None:
    dev = OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=-550)
    (slot,) = decode_slots(_snap(encode_onewire([dev])))
    assert slot.primary == -550


def test_bank_set_onewire_round_trip() -> None:
    bank = RegisterBank()
    dev = OneWireDevice(make_rom(FAMILY_DS2438, 3), primary=2210, secondary=3300)
    bank.set_onewire([dev], generation=2)
    bank.commit()
    (slot,) = decode_slots(bank.published())
    assert slot.usable and slot.primary == 2210 and slot.secondary == 3300
    resp = bank.handle_pdu(struct.pack(">BHH", 4, 140, 60))
    assert resp[0] == 4 and resp[1] == 120
    words = struct.unpack(">60H", resp[2:])
    assert words == tuple(encode_snapshot(bank.published())[40:100])
    assert words[0] == 1


def test_bank_set_onewire_atomic_on_error() -> None:
    bank = RegisterBank()
    bank.set_onewire([OneWireDevice(make_rom(FAMILY_DS18B20, 1), primary=100)])
    bad = OneWireDevice(make_rom(FAMILY_DS18B20, 2), primary=70000)
    with pytest.raises(ValueError):
        bank.set_onewire([bad])
    bank.commit()
    (slot,) = decode_slots(bank.published())
    assert slot.primary == 100


def test_usable_requires_present() -> None:
    reading = SlotReading(make_rom(FAMILY_DS18B20, 1), 2000, 0, SlotStatus.VALID)
    assert not reading.usable
    assert SlotReading(reading.rom, 2000, 0, SlotStatus.VALID | SlotStatus.PRESENT).usable


def test_rom_registers_carry_family_low_and_crc_high() -> None:
    rom = make_rom(FAMILY_DS18B20, 0x1234)
    fields = encode_onewire([OneWireDevice(rom, primary=1)])
    assert fields["onewire_s0_rom3"] & 0xFF == FAMILY_DS18B20
    assert fields["onewire_s0_rom0"] >> 8 == dallas_crc8(
        (rom & ((1 << 56) - 1)).to_bytes(7, "little")
    )
    assert fields["onewire_s0_rom0"] >> 8 == rom >> 56
