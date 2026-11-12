"""``ro-tools`` command-line interface.

Displays register contents only. It makes no accept/reject decision about a
snapshot and no claim that the system or water is safe.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import yaml
from loguru import logger

from ro_tools import codegen, schema
from ro_tools.client import CommsError, ModbusExceptionError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.presets import PRESETS, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer, serve_rtu_on

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COMMS = 2
EXIT_MODBUS = 3


def _names(enum_cls: type) -> list[str]:
    """Return the lower-cased member names of an enum.

    :param enum_cls: Enum class.
    :returns: Lower-cased member names in definition order.
    """
    return [member.name.lower() for member in enum_cls]  # type: ignore[attr-defined]


def _endpoint(parser: argparse.ArgumentParser) -> None:
    """Add the required, mutually exclusive ``--tcp`` / ``--serial`` group.

    :param parser: Sub-parser to extend.
    """
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tcp", metavar="HOST:PORT", help="Modbus-TCP endpoint")
    group.add_argument("--serial", metavar="DEVICE", help="serial device, e.g. COM5")


def _positive_float(text: str) -> float:
    """Argparse type for a strictly positive float.

    :param text: Argument text.
    :returns: The parsed value.
    :raises argparse.ArgumentTypeError: If not a number greater than zero.
    """
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be greater than 0, got {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    :returns: Parser with the five sub-commands.
    """
    parser = argparse.ArgumentParser(prog="ro-tools", description="RO protocol host tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate the register map")
    p.add_argument("path", nargs="?", type=Path, default=schema.DEFAULT_MAP_PATH)

    p = sub.add_parser("generate", help="regenerate generated/registers.py")
    p.add_argument("--check", action="store_true", help="write nothing; fail on drift")

    p = sub.add_parser("sim", help="run the simulated sensor node (SIMULATED VALUES ONLY)")
    _endpoint(p)
    p.add_argument("--preset", choices=PRESETS, default="healthy")
    p.add_argument("--period", type=_positive_float, default=1.0, metavar="SECONDS")

    p = sub.add_parser("read", help="read and print one snapshot")
    _endpoint(p)
    p.add_argument("--timeout", type=float, default=1.0, metavar="S")

    p = sub.add_parser("publish-status", help="write one display-only controller status block")
    _endpoint(p)
    p.add_argument("--state", required=True, choices=_names(reg.RoState))
    p.add_argument("--pump", choices=_names(reg.PumpCommanded), default="unknown")
    p.add_argument("--fault-code", type=int, default=0)
    p.add_argument("--severity", choices=_names(reg.FaultSeverity), default="none")
    p.add_argument("--fault-count", type=int, default=0)
    p.add_argument("--sequence", type=int, default=0)
    p.add_argument("--timeout", type=float, default=1.0, metavar="S")
    return parser


def _parse_tcp(parser: argparse.ArgumentParser, text: str) -> tuple[str, int]:
    """Split ``host:port`` on the last colon.

    :param parser: Parser used to report usage errors (raises ``SystemExit``).
    :param text: Endpoint text.
    :returns: ``(host, port)``.
    """
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isdecimal():
        parser.error(f"--tcp expects HOST:PORT, got {text!r}")
    return host, int(port)


def _cmd_validate(args: argparse.Namespace) -> int:
    """Validate a register map.

    :param args: Parsed arguments.
    :returns: Exit status.
    """
    try:
        m = schema.load(args.path)
    except schema.SchemaError as exc:
        for violation in exc.violations:
            print(violation, file=sys.stderr)
        return EXIT_FAIL
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot load {args.path}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(f"OK: protocol {m.version_major}.{m.version_minor}, {m.input_count} input words")
    return EXIT_OK


def _cmd_generate(args: argparse.Namespace) -> int:
    """Regenerate or check the generated codec module.

    :param args: Parsed arguments.
    :returns: Exit status.
    """
    try:
        m = schema.load()
    except schema.SchemaError as exc:
        for violation in exc.violations:
            print(violation, file=sys.stderr)
        return EXIT_FAIL
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot load register map: {exc}", file=sys.stderr)
        return EXIT_FAIL
    if args.check:
        if codegen.is_current(m):
            print("generated/registers.py is current")
            return EXIT_OK
        print(
            "generated/registers.py differs from register_map.yaml; run `ro-tools generate`",
            file=sys.stderr,
        )
        return EXIT_FAIL
    codegen.write(m)
    print("wrote generated/registers.py")
    return EXIT_OK


def _commit_loop(responder: Responder, period: float, alive: Callable[[], bool], what: str) -> int:
    """Commit a new snapshot every ``period`` seconds until interrupted.

    :param responder: Responder whose bank is committed.
    :param period: Seconds between commits.
    :param alive: Returns False if the server has died.
    :param what: Server description for the failure message.
    :returns: 0 on Ctrl-C, 1 if the server died.
    """
    try:
        while True:
            time.sleep(period)
            if not alive():
                print(f"simulator stopped unexpectedly: {what}", file=sys.stderr)
                return EXIT_FAIL
            responder.bank.commit()
    except KeyboardInterrupt:
        return EXIT_OK


def _cmd_sim(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the simulator until interrupted.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    endpoint = _parse_tcp(parser, args.tcp) if args.tcp is not None else None
    responder = Responder(RegisterBank())
    if endpoint is not None:
        try:
            server = TcpSimServer(responder, *endpoint)
            server.start()
        except OSError as exc:
            print(f"cannot start TCP simulator on {args.tcp}: {exc}", file=sys.stderr)
            return EXIT_FAIL
        apply_preset(responder, args.preset)
        print(f"SIMULATED VALUES ONLY - not equipment limits; preset={args.preset}", flush=True)
        logger.info("simulator listening on {}:{}", *server.address)
        try:
            return _commit_loop(responder, args.period, lambda: True, args.tcp)
        finally:
            server.stop()
    import serial

    try:
        port = serial.Serial(
            args.serial,
            baudrate=reg.SERIAL_BAUD,
            bytesize=8,
            parity=reg.SERIAL_PARITY,
            stopbits=reg.SERIAL_STOP_BITS,
            timeout=0.02,
        )
    except (serial.SerialException, OSError) as exc:
        print(f"cannot open serial port {args.serial}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    stop = threading.Event()
    thread = threading.Thread(target=serve_rtu_on, args=(responder, port, stop), daemon=True)
    try:
        apply_preset(responder, args.preset)
        print(f"SIMULATED VALUES ONLY - not equipment limits; preset={args.preset}", flush=True)
        thread.start()
        logger.info("simulator serving RTU on {}", args.serial)
        return _commit_loop(responder, args.period, thread.is_alive, args.serial)
    finally:
        stop.set()
        if thread.is_alive():
            thread.join(timeout=2.0)
        port.close()


def _open_client(parser: argparse.ArgumentParser, args: argparse.Namespace) -> SensorNodeClient:
    """Build a client for the chosen endpoint.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Unconnected client.
    """
    if args.tcp is not None:
        host, port = _parse_tcp(parser, args.tcp)
        return SensorNodeClient.tcp(host, port, timeout=args.timeout)
    return SensorNodeClient.serial(args.serial, timeout=args.timeout)


def _format_field(name: str, raw: int, by_name: dict[str, schema.Register]) -> str:
    """Format one snapshot field line.

    :param name: Field name.
    :param raw: Raw register value.
    :param by_name: Schema registers keyed by name.
    :returns: Display line.
    """
    line = f"{name:<27}{raw}"
    r = by_name.get(name)
    if r is not None and r.scale_divisor != 1:
        digits = len(str(r.scale_divisor)) - 1
        line += f"   ({raw / r.scale_divisor:.{digits}f} {r.unit})"
    return line


def _cmd_read(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Read and print one snapshot.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    client = _open_client(parser, args)
    try:
        by_name = {r.name: r for r in schema.load().input_registers}
        with client:
            snap = client.read_snapshot()
    except schema.SchemaError as exc:
        for violation in exc.violations:
            print(violation, file=sys.stderr)
        return EXIT_FAIL
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot load register map: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except CommsError as exc:
        print(f"communication failure: {exc}", file=sys.stderr)
        return EXIT_COMMS
    except ModbusExceptionError as exc:
        print(f"modbus exception: {exc}", file=sys.stderr)
        return EXIT_MODBUS
    for name, _typ, _offset in reg.SNAPSHOT_LAYOUT:
        print(_format_field(name, getattr(snap, name), by_name))
    mask = snap.validity_mask
    set_bits = "|".join(b.name for b in reg.ValidityBits if b.name and mask & b)
    print(f"validity: {set_bits}")
    all_set = (mask & reg.CRITICAL_VALIDITY) == reg.CRITICAL_VALIDITY
    print(f"critical validity bits all set: {'yes' if all_set else 'no'}")
    return EXIT_OK


def _cmd_publish_status(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Write one controller status block.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    status = reg.ControllerStatus(
        status_sequence=args.sequence,
        ro_state=reg.RoState[args.state.upper()],
        pump_commanded=reg.PumpCommanded[args.pump.upper()],
        controller_fault_code=args.fault_code,
        controller_fault_severity=reg.FaultSeverity[args.severity.upper()],
        controller_fault_count=args.fault_count,
    )
    client = _open_client(parser, args)
    try:
        with client:
            client.publish_status(status)
    except ValueError as exc:
        print(f"invalid status, nothing sent: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except CommsError as exc:
        print(f"communication failure: {exc}", file=sys.stderr)
        return EXIT_COMMS
    except ModbusExceptionError as exc:
        print(f"modbus exception: {exc}", file=sys.stderr)
        return EXIT_MODBUS
    print("status published")
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    :param argv: Arguments without the program name; ``sys.argv[1:]`` if None.
    :returns: Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "sim":
            return _cmd_sim(parser, args)
        if args.command == "read":
            return _cmd_read(parser, args)
        return _cmd_publish_status(parser, args)
    finally:
        logger.remove()
