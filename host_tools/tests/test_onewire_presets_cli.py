"""1-Wire simulator presets and the CLI ``read`` table (SIMULATED values)."""

import pytest

from ro_tools import cli
from ro_tools.generated.registers import FaultBits as F
from ro_tools.generated.registers import Snapshot
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    BusStatus,
    OneWireDevice,
    SlotStatus,
    decode_slots,
    encode_onewire,
    make_rom,
)
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import (
    FULL_PROFILE,
    PRESETS,
    RO_SKID_PROFILE,
    TANK_PROFILE,
    apply_preset,
)
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer

OW_PRESETS = ("onewire_healthy", "onewire_lost", "onewire_crc_error", "onewire_overflow")
OLD_PRESETS = tuple(p for p in PRESETS if p not in OW_PRESETS)
TEMP_ROM = make_rom(FAMILY_DS18B20, 1)
DS2438_ROM = make_rom(FAMILY_DS2438, 2)


def snap_of(preset, profile=FULL_PROFILE):
    responder = Responder(RegisterBank(), unit_id=1)
    apply_preset(responder, preset, profile)
    return responder.bank.published()


@pytest.mark.parametrize("name", OW_PRESETS)
def test_new_presets_registered(name):
    assert name in PRESETS


@pytest.mark.parametrize("profile", [FULL_PROFILE, RO_SKID_PROFILE, TANK_PROFILE])
def test_onewire_healthy_keeps_validity_and_no_fault(profile):
    snap = snap_of("onewire_healthy", profile)
    assert snap.validity_mask == snap_of("healthy", profile).validity_mask
    assert snap.fault_mask & F.ONEWIRE_BUS_FAULT == 0
    readings = decode_slots(snap)
    assert [r.rom for r in readings] == sorted([TEMP_ROM, DS2438_ROM])
    assert all(r.usable for r in readings)
    by_rom = {r.rom: r for r in readings}
    assert by_rom[TEMP_ROM].primary == 2150
    assert (by_rom[DS2438_ROM].primary, by_rom[DS2438_ROM].secondary) == (2210, 3300)
    assert snap.onewire_bus_status == 0


@pytest.mark.parametrize("name", OW_PRESETS[1:])
def test_degraded_onewire_presets_raise_fault_only(name):
    healthy = snap_of("healthy")
    snap = snap_of(name)
    assert snap.validity_mask == healthy.validity_mask
    assert snap.fault_mask & F.ONEWIRE_BUS_FAULT
    assert snap.fault_mask == int(F.ONEWIRE_BUS_FAULT)
    assert snap.module_status == healthy.module_status


def test_lost_preset_marks_missing():
    snap = snap_of("onewire_lost")
    by_rom = {r.rom: r for r in decode_slots(snap)}
    assert by_rom[TEMP_ROM].status & SlotStatus.MISSING
    assert not by_rom[TEMP_ROM].usable
    assert by_rom[DS2438_ROM].usable
    assert not snap.onewire_bus_status & BusStatus.NO_PRESENCE


def test_crc_and_overflow_presets_bus_status():
    crc = snap_of("onewire_crc_error")
    assert crc.onewire_bus_status == int(BusStatus.CRC_ERRORS)
    assert not {r.rom: r for r in decode_slots(crc)}[TEMP_ROM].usable
    over = snap_of("onewire_overflow")
    assert over.onewire_bus_status == int(BusStatus.OVERFLOW)
    assert len(decode_slots(over)) == 8


@pytest.mark.parametrize("name", OLD_PRESETS)
def test_old_presets_leave_onewire_block_zero(name):
    snap = snap_of(name)
    assert decode_slots(snap) == ()
    assert snap.onewire_device_count == 0
    assert snap.onewire_bus_status == 0
    assert snap.fault_mask & F.ONEWIRE_BUS_FAULT == 0


def test_sim_help_choices_come_from_presets():
    parser = cli.build_parser()
    args = parser.parse_args(["sim", "--tcp", "h:1", "--preset", "onewire_lost"])
    assert args.preset == "onewire_lost"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["sim", "--tcp", "h:1", "--preset", "no_such_preset"])
    assert exc.value.code == 2


def test_print_onewire_uses_real_slot_index_with_gap(capsys):
    a = OneWireDevice(TEMP_ROM, primary=2150)
    b = OneWireDevice(DS2438_ROM, primary=2210, secondary=3300)
    fields = encode_onewire([a, b])
    for name in list(fields):
        if name.startswith("onewire_s1_"):
            fields[name] = 0
    # Move the second device from slot 1 into slot 2 to create a gap.
    for suffix in ("rom0", "rom1", "rom2", "rom3", "primary", "secondary", "status"):
        fields[f"onewire_s2_{suffix}"] = encode_onewire([a, b])[f"onewire_s1_{suffix}"]
    snap = Snapshot(**fields)
    assert [r.slot for r in decode_slots(snap)] == [0, 2]
    cli._print_onewire(snap)
    rows = capsys.readouterr().out.splitlines()[2:]
    assert [row.split()[0] for row in rows] == ["0", "2"]


def test_read_bus_status_without_slots_prints_header_and_keeps_exit_code(capsys):
    responder = Responder(RegisterBank(), unit_id=1)
    apply_preset(responder, "healthy", RO_SKID_PROFILE)
    healthy_code, _ = read_with("healthy", capsys)
    responder.bank.set_field("onewire_bus_status", int(BusStatus.NO_PRESENCE))
    responder.bank.commit()
    bus = Bus()
    bus.add(responder)
    with TcpSimServer(bus) as server:
        host, port = server.address
        code = cli.main(["read", "--tcp", f"{host}:{port}"])
    out = capsys.readouterr().out
    assert code == healthy_code
    assert "1-Wire bus status: NO_PRESENCE" in out
    assert "slot" in out


def read_with(preset, capsys):
    responder = Responder(RegisterBank(), unit_id=1)
    apply_preset(responder, preset, RO_SKID_PROFILE)
    bus = Bus()
    bus.add(responder)
    with TcpSimServer(bus) as server:
        host, port = server.address
        code = cli.main(["read", "--tcp", f"{host}:{port}"])
    return code, capsys.readouterr().out


def test_read_healthy_onewire_table(capsys):
    code, out = read_with("onewire_healthy", capsys)
    assert code == read_with("healthy", capsys)[0]
    assert f"{TEMP_ROM:016X}" in out
    assert f"{DS2438_ROM:016X}" in out
    assert "DS18B20" in out and "DS2438" in out
    assert out.count("usable") == 2


def test_read_without_onewire_prints_no_table(capsys):
    _, out = read_with("healthy", capsys)
    assert "1-Wire" not in out


def test_read_lost_shows_missing_and_same_exit_code(capsys):
    healthy_code, healthy_out = read_with("healthy", capsys)
    code, out = read_with("onewire_lost", capsys)
    assert code == healthy_code
    assert "missing" in out
    assert out.count(" usable") == 1
    crit = "critical validity bits all set: yes"
    assert crit in out and crit in healthy_out


@pytest.mark.parametrize("name", OW_PRESETS)
def test_read_exit_code_unaffected(name, capsys):
    assert read_with(name, capsys)[0] == read_with("healthy", capsys)[0]
