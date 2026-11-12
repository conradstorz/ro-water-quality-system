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


def test_validate_missing_file_message(tmp_path, capsys):
    assert cli.main(["validate", str(tmp_path / "absent.yaml")]) == 1
    assert "absent.yaml" in capsys.readouterr().err


def test_generate_check_reports_drift(monkeypatch, capsys):
    monkeypatch.setattr(cli.codegen, "is_current", lambda m: False)
    assert cli.main(["generate", "--check"]) == 1
    assert "differs" in capsys.readouterr().err


def test_publish_status_comms_failure_exit_2(server):
    server.responder.drop_responses = True
    rc = cli.main(
        ["publish-status", "--tcp", _tcp(server), "--state", "standby", "--timeout", "0.3"]
    )
    assert rc == 2


@pytest.mark.parametrize(
    "extra", [["--fault-code", "70000"], ["--sequence", "-1"], ["--fault-count", "70000"]]
)
def test_publish_status_out_of_range_exit_1(server, capsys, extra):
    rc = cli.main(
        ["publish-status", "--tcp", _tcp(server), "--state", "standby", "--timeout", "0.5", *extra]
    )
    assert rc == 1
    assert capsys.readouterr().err.strip()
    assert server.responder.bank.controller_status is None


def test_sim_serial_unopenable_port_exits_1(capsys):
    assert cli.main(["sim", "--serial", "NO_SUCH_PORT_XYZ"]) == 1
    assert "NO_SUCH_PORT_XYZ" in capsys.readouterr().err


def test_sim_tcp_port_in_use_exits_1(capsys):
    import socket

    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        port = blocker.getsockname()[1]
        assert cli.main(["sim", "--tcp", f"127.0.0.1:{port}"]) == 1
    captured = capsys.readouterr()
    assert captured.err.strip()
    assert "SIMULATED" not in captured.out


def test_sim_bad_endpoint_prints_no_banner(capsys):
    with pytest.raises(SystemExit):
        cli.main(["sim", "--tcp", "no-port"])
    assert "SIMULATED" not in capsys.readouterr().out


@pytest.mark.parametrize("period", ["0", "-1", "abc"])
def test_parser_rejects_bad_period(period):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["sim", "--tcp", "a:1", "--period", period])


def test_read_bad_map_exits_1(server, monkeypatch, capsys):
    def boom():
        raise FileNotFoundError("map missing")

    monkeypatch.setattr(cli.schema, "load", boom)
    assert cli.main(["read", "--tcp", _tcp(server), "--timeout", "0.5"]) == 1
    assert "map missing" in capsys.readouterr().err


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_sim_serial_server_thread_death_exits_1(monkeypatch, capsys):
    import serial

    closed = []

    class DyingPort:
        def __init__(self, *args, **kwargs):
            pass

        def read(self, size=1):
            raise OSError("device unplugged")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(serial, "Serial", DyingPort)
    assert cli.main(["sim", "--serial", "COM99", "--period", "0.05"]) == 1
    assert "stopped unexpectedly" in capsys.readouterr().err
    assert closed


def test_verbose_flag_parses():
    parser = cli.build_parser()
    assert parser.parse_args(["validate"]).verbose is False
    assert parser.parse_args(["-v", "validate"]).verbose is True
    assert parser.parse_args(["--verbose", "validate"]).verbose is True


@pytest.mark.parametrize(("argv", "level"), [(["validate"], "INFO"), (["-v", "validate"], "DEBUG")])
def test_verbose_sets_loguru_level(monkeypatch, argv, level):
    levels = []
    monkeypatch.setattr(cli.logger, "add", lambda sink, **kw: levels.append(kw["level"]))
    assert cli.main(argv) == 0
    assert levels == [level]


@pytest.mark.parametrize("endpoint", ["127.0.0.1:70000", "127.0.0.1:65536"])
def test_tcp_port_out_of_range_is_usage_error(endpoint, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["read", "--tcp", endpoint])
    assert exc.value.code == 2
    assert "port" in capsys.readouterr().err


def test_tcp_port_boundaries_are_accepted():
    parser = cli.build_parser()
    assert cli._parse_tcp(parser, "h:0") == ("h", 0)
    assert cli._parse_tcp(parser, "h:65535") == ("h", 65535)


def test_sim_tcp_port_out_of_range_is_usage_error():
    with pytest.raises(SystemExit):
        cli.main(["sim", "--tcp", "127.0.0.1:70000"])


@pytest.mark.parametrize("cmd", [["read"], ["publish-status", "--state", "standby"]])
@pytest.mark.parametrize("timeout", ["0", "-1", "abc"])
def test_timeout_must_be_positive(cmd, timeout):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args([*cmd, "--tcp", "a:1", "--timeout", timeout])


@pytest.mark.parametrize(
    "extra", [["--fault-code", "70000"], ["--sequence", "-1"], ["--fault-count", "70000"]]
)
def test_publish_status_range_error_exits_before_connecting(monkeypatch, capsys, extra):
    def no_connect(*args, **kwargs):
        raise AssertionError("must not create a client")

    monkeypatch.setattr(cli.SensorNodeClient, "tcp", no_connect)
    rc = cli.main(["publish-status", "--tcp", "127.0.0.1:9", "--state", "standby", *extra])
    assert rc == 1
    assert "nothing sent" in capsys.readouterr().err


def test_publish_status_inconsistent_block_is_still_sent(server):
    """Only range errors are caught client-side; the node's rejection must stay testable."""
    rc = cli.main(
        ["publish-status", "--tcp", _tcp(server), "--state", "fault", "--fault-code", "1001"]
    )
    assert rc == 3


@pytest.mark.parametrize("argv", [["generate"], ["generate", "--check"]])
def test_generate_value_error_exits_1(monkeypatch, capsys, argv):
    def boom(*args, **kwargs):
        raise ValueError("cannot render")

    monkeypatch.setattr(cli.codegen, "render", boom)
    monkeypatch.setattr(cli.codegen, "write", boom)
    monkeypatch.setattr(cli.codegen, "is_current", boom)
    assert cli.main(argv) == 1
    assert "cannot render" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["inf", "1e309", "nan", "-inf"])
def test_non_finite_period_and_timeout_are_usage_errors(text):
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["sim", "--tcp", "127.0.0.1:5020", "--period", text])
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["read", "--tcp", "127.0.0.1:5020", "--timeout", text])


@pytest.mark.parametrize("argv", [["generate"], ["generate", "--check"]])
def test_generate_filesystem_error_exits_1(monkeypatch, capsys, argv):
    def boom(*args, **kwargs):
        raise PermissionError("read-only checkout")

    monkeypatch.setattr(cli.codegen, "write", boom)
    monkeypatch.setattr(cli.codegen, "is_current", boom)
    assert cli.main(argv) == 1
    assert "read-only checkout" in capsys.readouterr().err
