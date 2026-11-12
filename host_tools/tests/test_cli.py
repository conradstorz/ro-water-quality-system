"""CLI tests. The long-running `sim` command is covered by parser tests only."""

import pytest
import yaml

from ro_tools import cli, schema
from ro_tools.generated import registers as reg
from ro_tools.sim.presets import apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


@pytest.fixture()
def server():
    responder = Responder(RegisterBank())
    apply_preset(responder, "healthy")
    with TcpSimServer(responder) as srv:
        srv.responder = responder
        yield srv


def _tcp(server) -> str:
    return f"{server.address[0]}:{server.address[1]}"


def test_validate_ok(capsys):
    assert cli.main(["validate"]) == 0
    assert "OK: protocol 1.1, 40 input words" in capsys.readouterr().out


def test_validate_reports_violations(tmp_path, capsys):
    raw = yaml.safe_load(schema.DEFAULT_MAP_PATH.read_text(encoding="utf-8"))
    raw["input_registers"][3]["type"] = "u8"
    raw["fault_codes"][1]["source"] = "lcd"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert cli.main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert "module_status" in err and "lcd" in err


def test_validate_missing_file(tmp_path):
    assert cli.main(["validate", str(tmp_path / "absent.yaml")]) == 1


def test_generate_check_is_clean():
    assert cli.main(["generate", "--check"]) == 0


def test_read_prints_decoded_snapshot(server, capsys):
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.5"]) == 0
    out = capsys.readouterr().out
    assert "feed_ec_us_cm_x10" in out and "(425.7 uS/cm)" in out
    assert "critical validity bits all set: yes" in out
    assert "PERMEATE_EC" in out


def test_read_shows_missing_critical_validity(server, capsys):
    apply_preset(server.responder, "critical_sensor_invalid")
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.5"]) == 0
    assert "critical validity bits all set: no" in capsys.readouterr().out


def test_read_comms_failure_exit_2(server, capsys):
    server.responder.drop_responses = True
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.3"]) == 2


def test_publish_status(server):
    rc = cli.main(
        [
            "publish-status",
            "--tcp",
            _tcp(server),
            "--state",
            "production",
            "--pump",
            "on",
            "--sequence",
            "4",
            "--timeout",
            "0.5",
        ]
    )
    assert rc == 0
    st = server.responder.bank.controller_status
    assert (st.ro_state, st.pump_commanded, st.status_sequence) == (
        reg.RoState.PRODUCTION,
        reg.PumpCommanded.ON,
        4,
    )


def test_publish_status_with_fault(server):
    rc = cli.main(
        [
            "publish-status",
            "--tcp",
            _tcp(server),
            "--state",
            "fault",
            "--fault-code",
            "1001",
            "--severity",
            "critical",
            "--fault-count",
            "1",
            "--timeout",
            "0.5",
        ]
    )
    assert rc == 0
    assert server.responder.bank.controller_status.controller_fault_code == 1001


def test_publish_inconsistent_status_exit_3(server):
    rc = cli.main(
        [
            "publish-status",
            "--tcp",
            _tcp(server),
            "--state",
            "fault",
            "--fault-code",
            "1001",
            "--timeout",
            "0.5",
        ]
    )
    assert rc == 3
    assert server.responder.bank.controller_status is None


def test_parser_sim_options():
    args = cli.build_parser().parse_args(["sim", "--tcp", "127.0.0.1:5020", "--preset", "stale"])
    assert args.preset == "stale" and args.tcp == "127.0.0.1:5020" and args.period == 1.0


@pytest.mark.parametrize(
    "argv",
    [
        ["sim"],
        ["sim", "--tcp", "a:1", "--serial", "COM5"],
        ["sim", "--tcp", "a:1", "--preset", "nope"],
        ["read"],
        ["publish-status", "--tcp", "a:1"],
        ["publish-status", "--tcp", "a:1", "--state", "bogus"],
        [],
    ],
)
def test_parser_rejects(argv):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(argv)


def test_bad_tcp_endpoint_is_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["read", "--tcp", "no-port"])
