"""``ro-tools onewire scan|validate|push`` against the in-process simulator (SIMULATED values)."""

from pathlib import Path

import pytest
import yaml
from test_name_table_isolation import _bus, _observe

import ro_tools.client as client_mod
from ro_tools import cli
from ro_tools.client import SensorNodeClient
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    SlotReading,
    SlotStatus,
    format_rom,
    make_rom,
    rom_family,
)
from ro_tools.onewire_names import (
    DEFAULT_BINDINGS_PATH,
    bindings_revision,
    decode_name_table,
    load_bindings,
    validate_bindings_data,
)
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import NAMED_ENTRIES, RO_SKID_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer

_BY_FAMILY = {rom_family(e.rom): e.rom for e in NAMED_ENTRIES}
TEMP_ROM, DS2438_ROM = _BY_FAMILY[FAMILY_DS18B20], _BY_FAMILY[FAMILY_DS2438]
ROLES = {TEMP_ROM: ("outside_temp", "Outside air"), DS2438_ROM: ("tank_air", "Tank air")}


def _write_bindings(path: Path, roms: list[int]) -> Path:
    devices = [
        {"rom": format_rom(rom), "role": ROLES[rom][0], "label": ROLES[rom][1]} for rom in roms
    ]
    path.write_text(yaml.safe_dump({"schema": 1, "devices": devices}), encoding="utf-8")
    return path


@pytest.fixture()
def node():
    """One protocol 1.4 RO-skid node on unit 3 with the DS18B20 + DS2438 pair, no names."""
    responder = Responder(RegisterBank(), unit_id=3)
    apply_preset(responder, "onewire_healthy", RO_SKID_PROFILE)
    bus = Bus()
    bus.add(responder)
    with TcpSimServer(bus) as srv:
        srv.responder = responder
        yield srv


def _ep(srv) -> list[str]:
    return ["--tcp", f"{srv.address[0]}:{srv.address[1]}", "--unit-id", "3", "--timeout", "0.5"]


def _run(*argv: str) -> int:
    return cli.main(["onewire", *argv])


# ---------------------------------------------------------------- scan


def test_scan_all_bound(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM, DS2438_ROM])
    assert _run("scan", *_ep(node), "--bindings", str(path)) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()
    temp = next(line for line in lines if line.startswith(format_rom(TEMP_ROM)))
    ds = next(line for line in lines if line.startswith(format_rom(DS2438_ROM)))
    assert "DS18B20" in temp and "21.50 degC" in temp and "outside_temp" in temp
    assert "'Outside air'" in temp
    assert "DS2438" in ds and "22.10 degC" in ds and "3300 mV" in ds and "tank_air" in ds
    assert "UNBOUND" not in out and "TODO" not in out


def test_scan_unbound_prints_quoted_stubs(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [])
    assert _run("scan", *_ep(node), "--bindings", str(path)) == 0
    out = capsys.readouterr().out
    assert out.count("UNBOUND") == 2
    for rom in (TEMP_ROM, DS2438_ROM):
        assert f'- rom: "{format_rom(rom)}"\n  role: TODO\n  label: TODO' in out


def test_scan_mixed(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [DS2438_ROM])
    assert _run("scan", *_ep(node), "--bindings", str(path)) == 0
    out = capsys.readouterr().out
    assert out.count("UNBOUND") == 1
    assert f'- rom: "{format_rom(TEMP_ROM)}"' in out
    assert f'"{format_rom(DS2438_ROM)}"' not in out
    assert "tank_air" in out


def test_scan_missing_bindings_file(node, tmp_path, capsys):
    assert _run("scan", *_ep(node), "--bindings", str(tmp_path / "absent.yaml")) == 0
    out = capsys.readouterr().out
    assert "not found" in out and "unbound" in out
    assert out.count("UNBOUND") == 2


def test_scan_invalid_bindings_exit_1_without_reading(node, tmp_path, capsys):
    bad = tmp_path / "b.yaml"
    bad.write_text("schema: 2\ndevices: []\n", encoding="utf-8")
    node.responder.drop_responses = True  # a read attempt would be a comms failure (exit 2)
    assert _run("scan", *_ep(node), "--bindings", str(bad)) == 1
    assert "schema" in capsys.readouterr().err


def test_scan_no_devices(tmp_path, capsys):
    responder = Responder(RegisterBank(), unit_id=3)
    apply_preset(responder, "healthy", RO_SKID_PROFILE)
    bus = Bus()
    bus.add(responder)
    with TcpSimServer(bus) as srv:
        assert _run("scan", *_ep(srv), "--bindings", str(tmp_path / "absent.yaml")) == 0
    assert "no 1-Wire devices present" in capsys.readouterr().out


def test_scan_works_on_protocol_13_node(capsys, tmp_path):
    responder = Responder(RegisterBank(names_supported=False), unit_id=3)
    apply_preset(responder, "onewire_healthy", RO_SKID_PROFILE)
    bus = Bus()
    bus.add(responder)
    with TcpSimServer(bus) as srv:
        assert _run("scan", *_ep(srv), "--bindings", str(tmp_path / "absent.yaml")) == 0
    assert capsys.readouterr().out.count("UNBOUND") == 2


def test_scan_comms_failure_exit_2(node, tmp_path):
    node.responder.drop_responses = True
    argv = ["scan", "--tcp", f"{node.address[0]}:{node.address[1]}", "--unit-id", "3"]
    assert _run(*argv, "--timeout", "0.3", "--bindings", str(tmp_path / "x.yaml")) == 2


def _slot(rom: int, status: SlotStatus, primary: int = 2150, secondary: int = 0) -> SlotReading:
    return SlotReading(rom=rom, primary=primary, secondary=secondary, status=status)


OK = SlotStatus.PRESENT | SlotStatus.VALID


@pytest.mark.parametrize(
    ("slot", "family", "reading"),
    [
        (_slot(TEMP_ROM, OK, -125), "DS18B20", "-1.25 degC"),
        (_slot(DS2438_ROM, OK, 2210, 3300), "DS2438", "22.10 degC  3300 mV"),
        (_slot(TEMP_ROM, OK | SlotStatus.STALE), "DS18B20", "---"),
        (_slot(TEMP_ROM, SlotStatus.PRESENT), "DS18B20", "---"),
        (_slot(TEMP_ROM, SlotStatus(0x8000) | OK), "DS18B20", "---"),
        (_slot(make_rom(0x10, 5), OK | SlotStatus.UNSUPPORTED_FAMILY), "unknown 0x10", "---"),
        (_slot(make_rom(0x10, 5), OK), "unknown 0x10", "---"),
    ],
)
def test_scan_row_formatting(slot, family, reading):
    assert cli._scan_family(slot.rom) == family
    assert cli._scan_reading(slot) == reading


def _all_digit_rom() -> int:
    for n in range(1, 100_000):
        rom = make_rom(FAMILY_DS18B20, int(str(n), 16))
        if format_rom(rom).isdigit():
            return rom
    raise AssertionError("no all-digit ROM found")


@pytest.mark.parametrize("rom", [_all_digit_rom(), make_rom(FAMILY_DS2438, 0xABCDEF)])
@pytest.mark.parametrize("indent", ["", "  "])
def test_stub_is_quoted_and_validates_once_filled(rom, indent, tmp_path):
    stub = cli.yaml_stub(rom)
    assert stub.splitlines()[0] == f'- rom: "{format_rom(rom)}"'
    pasted = "".join(f"{indent}{line}\n" for line in stub.splitlines())
    todo = yaml.safe_load("schema: 1\ndevices:\n" + pasted)
    assert isinstance(todo["devices"][0]["rom"], str)
    assert any("role" in v for v in validate_bindings_data(todo))  # TODO is not a valid role
    filled = pasted.replace("role: TODO", "role: new_probe").replace(
        "label: TODO", "label: New probe"
    )
    path = tmp_path / "b.yaml"
    path.write_text("schema: 1\ndevices:\n" + filled, encoding="utf-8")
    (binding,) = load_bindings(path)
    assert (binding.rom, binding.role, binding.label) == (rom, "new_probe", "New probe")
    assert cli.main(["onewire", "validate", "--bindings", str(path)]) == 0


def test_all_digit_rom_unquoted_would_break():
    """Why the stub quotes: an unquoted all-digit ROM loads as an int."""
    text = format_rom(_all_digit_rom())
    assert not isinstance(yaml.safe_load(f"rom: {text}")["rom"], str)


# ---------------------------------------------------------------- validate


def test_validate_ok(tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM, DS2438_ROM])
    assert _run("validate", "--bindings", str(path)) == 0
    assert "OK: 2 1-Wire device(s)" in capsys.readouterr().out


def test_validate_default_file_ok(capsys):
    assert _run("validate") == 0
    n = len(load_bindings(DEFAULT_BINDINGS_PATH))
    assert f"OK: {n} 1-Wire device(s)" in capsys.readouterr().out


def test_validate_bad_prints_every_violation(tmp_path, capsys):
    bad = tmp_path / "b.yaml"
    rom = format_rom(TEMP_ROM)
    bad.write_text(
        f"schema: 1\ndevices:\n"
        f"- {{rom: '{rom}', role: Bad, label: ok}}\n"
        f"- {{rom: '{rom}', role: two, label: '{'x' * 13}'}}\n",
        encoding="utf-8",
    )
    assert _run("validate", "--bindings", str(bad)) == 1
    err = capsys.readouterr().err
    assert "devices[0].role" in err
    assert "devices[1].rom: duplicate" in err
    assert "devices[1].label" in err


def test_validate_missing_file(tmp_path, capsys):
    assert _run("validate", "--bindings", str(tmp_path / "absent.yaml")) == 1
    assert "cannot read" in capsys.readouterr().err


# ---------------------------------------------------------------- push


def test_push_success_with_read_back(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [DS2438_ROM, TEMP_ROM])
    assert _run("push", *_ep(node), "--bindings", str(path)) == 0
    out = capsys.readouterr().out
    assert "pushed 2 name(s)" in out
    assert f"Outside air -> {format_rom(TEMP_ROM)}" in out
    assert f"Tank air    -> {format_rom(DS2438_ROM)}" in out
    revision, entries = decode_name_table(node.responder.bank.name_table_words)
    assert revision == bindings_revision(path)
    assert entries == NAMED_ENTRIES  # sorted by ROM, labels from the file


def test_push_only_sends_present_roms(node, tmp_path, capsys):
    absent = make_rom(FAMILY_DS18B20, 0x77)
    path = tmp_path / "b.yaml"
    devices = [
        {"rom": format_rom(TEMP_ROM), "role": "outside_temp", "label": "Outside air"},
        {"rom": format_rom(absent), "role": "elsewhere", "label": "Elsewhere"},
    ]
    path.write_text(yaml.safe_dump({"schema": 1, "devices": devices}), encoding="utf-8")
    assert _run("push", *_ep(node), "--bindings", str(path)) == 0
    _, entries = decode_name_table(node.responder.bank.name_table_words)
    assert [e.rom for e in entries] == [TEMP_ROM]
    assert "Elsewhere" not in capsys.readouterr().out


def test_push_no_bound_devices_writes_empty_table(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [])
    assert _run("push", *_ep(node), "--bindings", str(path)) == 0
    assert "pushed 0 name(s)" in capsys.readouterr().out
    assert decode_name_table(node.responder.bank.name_table_words) == (
        bindings_revision(path),
        (),
    )


def test_push_to_protocol_13_node_exit_4(tmp_path, capsys):
    responder = Responder(RegisterBank(names_supported=False), unit_id=3)
    apply_preset(responder, "onewire_healthy", RO_SKID_PROFILE)
    bus = Bus()
    bus.add(responder)
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM, DS2438_ROM])
    with TcpSimServer(bus) as srv:
        assert _run("push", *_ep(srv), "--bindings", str(path)) == 4
    assert "node does not support names (protocol 1.3?)" in capsys.readouterr().err


@pytest.mark.parametrize("content", ["schema: 1\ndevices:\n- {rom: nothex}\n", None])
def test_push_invalid_or_missing_bindings_exit_1_and_writes_nothing(node, tmp_path, content):
    path = tmp_path / "b.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert _run("push", *_ep(node), "--bindings", str(path)) == 1
    assert not any(node.responder.bank.name_table_words)


def test_push_read_back_mismatch_exit_1(node, tmp_path, monkeypatch, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM])
    monkeypatch.setattr(SensorNodeClient, "read_name_table", lambda self: None)
    assert _run("push", *_ep(node), "--bindings", str(path)) == 1
    assert "read-back mismatch" in capsys.readouterr().err


def test_push_rejected_table_exit_3(node, tmp_path, monkeypatch, capsys):
    """A table the node rejects (ILLEGAL_DATA_VALUE) is a Modbus exception, not 'unsupported'."""
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM])
    original = client_mod.encode_name_table
    # names_schema_major != 1: the node rejects the whole write.
    monkeypatch.setattr(client_mod, "encode_name_table", lambda e, r: [2, *original(e, r)[1:]])
    assert _run("push", *_ep(node), "--bindings", str(path)) == 3
    assert "does not support" not in capsys.readouterr().err


def test_push_comms_failure_exit_2(node, tmp_path, capsys):
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM])
    node.responder.drop_responses = True
    argv = ["push", "--tcp", f"{node.address[0]}:{node.address[1]}", "--unit-id", "3"]
    assert _run(*argv, "--timeout", "0.3", "--bindings", str(path)) == 2
    assert "communication failure" in capsys.readouterr().err


@pytest.mark.parametrize("preset", ["onewire_healthy", "critical_sensor_invalid", "stale"])
def test_push_never_changes_snapshot_health_or_permit(preset, tmp_path):
    path = _write_bindings(tmp_path / "b.yaml", [TEMP_ROM, DS2438_ROM])
    baseline = _bus(preset, True)
    written = _bus(preset, True)
    with TcpSimServer(written) as srv:
        for unit in written.unit_ids:
            ep = ["--tcp", f"{srv.address[0]}:{srv.address[1]}", "--unit-id", str(unit)]
            assert _run("push", *ep, "--timeout", "0.5", "--bindings", str(path)) == 0
    pushed = [written.node(u).bank.name_table_words for u in written.unit_ids]
    assert all(any(words) for words in pushed)  # the push really happened
    assert _observe(written) == _observe(baseline)
    for b in (baseline, written):
        for unit in b.unit_ids:
            b.node(unit).bank.commit()
    assert _observe(written) == _observe(baseline)


def test_parser_requires_endpoint_for_scan_and_push():
    parser = cli.build_parser()
    for sub in ("scan", "push"):
        with pytest.raises(SystemExit):
            parser.parse_args(["onewire", sub])
    args = parser.parse_args(["onewire", "validate"])
    assert args.bindings == cli.DEFAULT_BINDINGS_PATH
