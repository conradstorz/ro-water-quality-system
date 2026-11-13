"""CLI support for unit ids and a multi-node simulator."""

import pytest

from ro_tools import cli
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


def test_read_unit_id_option():
    args = cli.build_parser().parse_args(["read", "--tcp", "h:1", "--unit-id", "2"])
    assert args.unit_id == 2
    assert cli.build_parser().parse_args(["read", "--tcp", "h:1"]).unit_id == 1


@pytest.mark.parametrize("bad", ["0", "16", "x"])
def test_read_unit_id_out_of_range_exits_2(bad):
    with pytest.raises(SystemExit) as exc:
        cli.build_parser().parse_args(["read", "--tcp", "h:1", "--unit-id", bad])
    assert exc.value.code == 2


def test_sim_nodes_option_default_is_none():
    assert cli.build_parser().parse_args(["sim", "--tcp", "h:1"]).nodes is None


def test_parse_nodes_accepts_two_nodes():
    parser = cli.build_parser()
    assert cli._parse_nodes(parser, "ro_skid:1,tank:2") == [("ro_skid", 1), ("tank", 2)]


@pytest.mark.parametrize("text", ["ro_skid", "tank:0", "tank:16", "pump:1", "tank:1,tank:1", ""])
def test_parse_nodes_rejects_bad_specs(text):
    with pytest.raises(SystemExit) as exc:
        cli._parse_nodes(cli.build_parser(), text)
    assert exc.value.code == 2


def test_read_selects_the_requested_node(capsys):
    bus = Bus()
    for unit_id, profile in ((1, RO_SKID_PROFILE), (2, TANK_PROFILE)):
        responder = Responder(RegisterBank(), unit_id=unit_id)
        apply_preset(responder, "healthy", profile)
        bus.add(responder)
    with TcpSimServer(bus) as server:
        host, port = server.address
        assert cli.main(["read", "--tcp", f"{host}:{port}", "--unit-id", "2"]) == 0
    out = capsys.readouterr().out
    assert "node_type                  1" in out
    assert "installed_mask             " in out


def test_sim_nodes_pressure_failed_on_tank_fails_cleanly(capsys):
    code = cli.main(
        [
            "sim",
            "--tcp",
            "127.0.0.1:0",
            "--nodes",
            "ro_skid:1,tank:2",
            "--preset",
            "pressure_failed",
        ]
    )
    assert code == 1
    assert capsys.readouterr().err.strip() != ""


def test_pressure_failed_is_a_preset_choice():
    args = cli.build_parser().parse_args(["sim", "--tcp", "h:1", "--preset", "pressure_failed"])
    assert args.preset == "pressure_failed"
