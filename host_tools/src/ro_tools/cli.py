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

from ro_tools import bringup_capture, codegen, schema
from ro_tools.client import CommsError, ModbusExceptionError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.monitor import OneWireBinding, _slot_unusable_cause, critical_required
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    BusStatus,
    SlotReading,
    SlotStatus,
    decode_slots,
    format_rom,
    rom_family,
)
from ro_tools.onewire_names import (
    DEFAULT_BINDINGS_PATH,
    LABEL_MAX_CHARS,
    BindingsError,
    NameEntry,
    bindings_revision,
    load_bindings,
    select_for_node,
)
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import PRESETS, RO_SKID_PROFILE, TANK_PROFILE, NodeProfile, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer, open_serial_port, serve_rtu_on

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_COMMS = 2
EXIT_MODBUS = 3
#: ``onewire push``: the node answered ILLEGAL_DATA_ADDRESS (no name table, protocol 1.3?).
EXIT_NAMES_UNSUPPORTED = 4
_ILLEGAL_DATA_ADDRESS = 0x02


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


_NODE_PROFILES: dict[str, NodeProfile] = {"ro_skid": RO_SKID_PROFILE, "tank": TANK_PROFILE}


def _unit_id(text: str) -> int:
    """Parse a Modbus unit id in 1..15 (the node-ID jumper range).

    :param text: Command-line text.
    :returns: The unit id.
    :raises argparse.ArgumentTypeError: If not an integer in 1..15.
    """
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not an integer") from None
    if not 1 <= value <= 15:
        raise argparse.ArgumentTypeError(f"unit id {value} outside 1..15")
    return value


def _parse_nodes(parser: argparse.ArgumentParser, text: str) -> list[tuple[str, int]]:
    """Parse ``TYPE:ID[,TYPE:ID...]`` for ``sim --nodes``.

    :param parser: Parser for usage errors.
    :param text: The option value, e.g. ``ro_skid:1,tank:2``.
    :returns: ``(node type name, unit id)`` pairs in the order given.
    """
    nodes: list[tuple[str, int]] = []
    seen: set[int] = set()
    for item in text.split(","):
        kind, sep, ident = item.partition(":")
        if not sep or kind not in _NODE_PROFILES:
            parser.error(f"--nodes: {item!r} must be TYPE:ID with TYPE in {sorted(_NODE_PROFILES)}")
        try:
            unit = _unit_id(ident)
        except argparse.ArgumentTypeError as exc:
            parser.error(f"--nodes: {item!r}: {exc}")
        if unit in seen:
            parser.error(f"--nodes: unit id {unit} used twice")
        seen.add(unit)
        nodes.append((kind, unit))
    return nodes


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
    if not value > 0 or value == float("inf"):
        raise argparse.ArgumentTypeError(f"must be a finite number greater than 0, got {text!r}")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    :returns: Parser with the seven sub-commands.
    """
    parser = argparse.ArgumentParser(prog="ro-tools", description="RO protocol host tools")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="log at DEBUG level (default INFO)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="validate the register map")
    p.add_argument("path", nargs="?", type=Path, default=schema.DEFAULT_MAP_PATH)

    p = sub.add_parser("generate", help="regenerate registers.py and ro_registers.hpp")
    p.add_argument("--check", action="store_true", help="write nothing; fail on drift")

    p = sub.add_parser("sim", help="run the simulated sensor node (SIMULATED VALUES ONLY)")
    _endpoint(p)
    p.add_argument("--preset", choices=PRESETS, default="healthy")
    p.add_argument("--period", type=_positive_float, default=1.0, metavar="SECONDS")
    p.add_argument(
        "--nodes",
        default=None,
        metavar="TYPE:ID[,...]",
        help="simulate several nodes, e.g. ro_skid:1,tank:2 (default: one full node, unit 1)",
    )

    p = sub.add_parser("read", help="read and print one snapshot")
    _endpoint(p)
    p.add_argument("--unit-id", type=_unit_id, default=reg.UNIT_ID, metavar="N")
    p.add_argument("--timeout", type=_positive_float, default=1.0, metavar="S")

    p = sub.add_parser("publish-status", help="write one display-only controller status block")
    _endpoint(p)
    p.add_argument("--state", required=True, choices=_names(reg.RoState))
    p.add_argument("--pump", choices=_names(reg.PumpCommanded), default="unknown")
    p.add_argument("--fault-code", type=int, default=0)
    p.add_argument("--severity", choices=_names(reg.FaultSeverity), default="none")
    p.add_argument("--fault-count", type=int, default=0)
    p.add_argument("--sequence", type=int, default=0)
    p.add_argument("--timeout", type=_positive_float, default=1.0, metavar="S")

    p = sub.add_parser("onewire", help="1-Wire device names (bindings file and name table)")
    ow = p.add_subparsers(dest="onewire_command", required=True)
    for name, text in (
        ("scan", "list a node's 1-Wire devices and print YAML stubs for unbound ROMs"),
        ("push", "write a node's display-only name table and read it back"),
    ):
        q = ow.add_parser(name, help=text)
        _endpoint(q)
        q.add_argument("--unit-id", type=_unit_id, default=reg.UNIT_ID, metavar="N")
        q.add_argument("--timeout", type=_positive_float, default=1.0, metavar="S")
        q.add_argument("--bindings", type=Path, default=DEFAULT_BINDINGS_PATH, metavar="PATH")
    q = ow.add_parser("validate", help="check the 1-Wire bindings file")
    q.add_argument("--bindings", type=Path, default=DEFAULT_BINDINGS_PATH, metavar="PATH")

    p = sub.add_parser(
        "bringup", help="capture the sensor-node bring-up probe report (firmware/bringup)"
    )
    p.add_argument("--port", required=True, metavar="DEVICE", help='"COM" (CH343) port, e.g. COM5')
    p.add_argument(
        "--pre-erase",
        action="store_true",
        help="run read-only esptool/espefuse commands only (before erasing the factory image)",
    )
    p.add_argument("--logs", type=Path, default=bringup_capture.DEFAULT_LOG_DIR, metavar="DIR")
    p.add_argument("--timeout", type=_positive_float, default=120.0, metavar="S")
    p.add_argument(
        "--no-reset",
        action="store_true",
        help="do not reset the board; send 'report' instead",
    )
    return parser


def _parse_tcp(parser: argparse.ArgumentParser, text: str) -> tuple[str, int]:
    """Split ``host:port`` on the last colon.

    :param parser: Parser used to report usage errors (raises ``SystemExit``).
    :param text: Endpoint text.
    :returns: ``(host, port)`` with ``port`` in 0..65535.
    """
    host, sep, port = text.rpartition(":")
    if not sep or not host or not port.isascii() or not port.isdecimal():
        parser.error(f"--tcp expects HOST:PORT, got {text!r}")
    if int(port) > 65535:
        parser.error(f"--tcp port must be 0..65535, got {port}")
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
    """Regenerate or check the generated Python module and C++ header.

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
    try:
        if args.check:
            status = EXIT_OK
            for label, is_current in (
                ("generated/registers.py", codegen.is_current),
                (codegen.CPP_PATH.name, codegen.is_cpp_current),
            ):
                if is_current(m):
                    print(f"{label} is current")
                else:
                    print(
                        f"{label} differs from register_map.yaml; run `ro-tools generate`",
                        file=sys.stderr,
                    )
                    status = EXIT_FAIL
            return status
        codegen.write(m)
        codegen.write_cpp(m)
    except (ValueError, OSError) as exc:
        print(f"cannot generate registers.py or ro_registers.hpp: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print("wrote generated/registers.py")
    print(f"wrote {codegen.CPP_PATH.name}")
    return EXIT_OK


def _commit_loop(
    responders: Sequence[Responder], period: float, alive: Callable[[], bool], what: str
) -> int:
    """Commit a new snapshot on every bank each ``period`` seconds until interrupted.

    :param responders: Responders whose banks are committed.
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
            for responder in responders:
                responder.bank.commit()
    except KeyboardInterrupt:
        return EXIT_OK


def _build_multi_node(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> tuple[Bus, list[Responder]] | None:
    """Build the simulated bus for ``--nodes``.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: The bus and its responders, or None (message printed) if a preset
        does not apply to a node type.
    """
    bus = Bus()
    responders: list[Responder] = []
    for kind, unit in _parse_nodes(parser, args.nodes):
        responder = Responder(RegisterBank(), unit_id=unit)
        try:
            apply_preset(responder, args.preset, _NODE_PROFILES[kind])
        except ValueError as exc:
            print(f"cannot apply preset {args.preset!r} to {kind}:{unit}: {exc}", file=sys.stderr)
            return None
        bus.add(responder)
        responders.append(responder)
    return bus, responders


def _cmd_sim(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Run the simulator until interrupted.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    endpoint = _parse_tcp(parser, args.tcp) if args.tcp is not None else None
    multi = args.nodes is not None
    if multi:
        # Presets are applied before any port or socket is opened, so a bad
        # preset/node combination leaves nothing to clean up.
        built = _build_multi_node(parser, args)
        if built is None:
            return EXIT_FAIL
        target: Responder | Bus = built[0]
        responders = built[1]
    else:
        single = Responder(RegisterBank())
        target = single
        responders = [single]
    if endpoint is not None:
        try:
            server = TcpSimServer(target, *endpoint)
            server.start()
        except OSError as exc:
            print(f"cannot start TCP simulator on {args.tcp}: {exc}", file=sys.stderr)
            return EXIT_FAIL
        if not multi:
            apply_preset(responders[0], args.preset)
        print(f"SIMULATED VALUES ONLY - not equipment limits; preset={args.preset}", flush=True)
        logger.info("simulator listening on {}:{}", *server.address)
        try:
            return _commit_loop(responders, args.period, lambda: True, args.tcp)
        finally:
            server.stop()
    import serial

    try:
        port = open_serial_port(args.serial)
    except (serial.SerialException, OSError) as exc:
        print(f"cannot open serial port {args.serial}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    stop = threading.Event()
    thread = threading.Thread(target=serve_rtu_on, args=(target, port, stop), daemon=True)
    try:
        if not multi:
            apply_preset(responders[0], args.preset)
        print(f"SIMULATED VALUES ONLY - not equipment limits; preset={args.preset}", flush=True)
        thread.start()
        logger.info("simulator serving RTU on {}", args.serial)
        return _commit_loop(responders, args.period, thread.is_alive, args.serial)
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
    unit_id = getattr(args, "unit_id", reg.UNIT_ID)
    if args.tcp is not None:
        host, port = _parse_tcp(parser, args.tcp)
        return SensorNodeClient.tcp(host, port, unit_id=unit_id, timeout=args.timeout)
    return SensorNodeClient.serial(args.serial, unit_id=unit_id, timeout=args.timeout)


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


def _family_name(rom: int) -> str:
    """Name the 1-Wire family of a ROM.

    :param rom: 64-bit ROM id.
    :returns: Family name or ``unsupported 0xNN``.
    """
    family = rom_family(rom)
    if family == FAMILY_DS18B20:
        return "DS18B20"
    if family == FAMILY_DS2438:
        return "DS2438"
    return f"unsupported 0x{family:02X}"


def _onewire_row(index: int, reading: SlotReading) -> str:
    """Format one 1-Wire slot row.

    :param index: Slot number.
    :param reading: Decoded slot.
    :returns: Table row.
    """
    flags = [f.name.lower() for f in SlotStatus if f.name and reading.status & f]
    if reading.usable:
        flags.append("usable")
    return (
        f"{index:<5}{reading.rom:016X}  {_family_name(reading.rom):<17}"
        f"{reading.primary:>8}{reading.secondary:>10}  {' '.join(flags)}"
    )


def _print_onewire(snap: reg.Snapshot) -> None:
    """Print the 1-Wire table (display only; never affects the exit status).

    :param snap: Decoded snapshot.
    """
    slots = decode_slots(snap)
    if not slots and not snap.onewire_bus_status:
        return
    bus = "|".join(b.name for b in BusStatus if b.name and snap.onewire_bus_status & b)
    print(f"1-Wire bus status: {bus or 'none'}")
    print(f"{'slot':<5}{'rom':<18}{'family':<17}{'primary':>8}{'secondary':>10}  status")
    for reading in slots:
        print(_onewire_row(reading.slot, reading))


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
    try:
        type_name = reg.NodeType(snap.node_type).name
    except ValueError:
        type_name = str(snap.node_type)
    print(f"node type: {type_name}")
    print(f"installed_mask: 0x{snap.installed_mask:04X}")
    needed = critical_required(snap.installed_mask)
    all_set = (mask & needed) == needed
    print(f"critical validity bits all set: {'yes' if all_set else 'no'}")
    if mask & ~snap.installed_mask:
        print(
            "WARNING: validity bits outside installed_mask "
            f"(0x{mask & ~snap.installed_mask:04X}); node violates protocol invariant"
        )
    _print_onewire(snap)
    return EXIT_OK


def _cmd_publish_status(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Write one controller status block.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    status = reg.ControllerStatus(
        status_schema_major=reg.STATUS_SCHEMA_MAJOR,
        status_sequence=args.sequence,
        ro_state=reg.RoState[args.state.upper()],
        pump_commanded=reg.PumpCommanded[args.pump.upper()],
        controller_fault_code=args.fault_code,
        controller_fault_severity=reg.FaultSeverity[args.severity.upper()],
        controller_fault_count=args.fault_count,
        controller_flags=0,
    )
    try:
        # Range check only: validate_status is deliberately not run here, so an
        # inconsistent block still reaches the node and its own rejection.
        reg.encode_status(status)
    except ValueError as exc:
        print(f"invalid status, nothing sent: {exc}", file=sys.stderr)
        return EXIT_FAIL
    client = _open_client(parser, args)
    try:
        with client:
            client.publish_status(status)
    except CommsError as exc:
        print(f"communication failure: {exc}", file=sys.stderr)
        return EXIT_COMMS
    except ModbusExceptionError as exc:
        print(f"modbus exception: {exc}", file=sys.stderr)
        return EXIT_MODBUS
    print("status published")
    return EXIT_OK


def _load_bindings_or_report(path: Path) -> tuple[OneWireBinding, ...] | None:
    """Load a bindings file, printing every problem on stderr.

    :param path: Bindings file.
    :returns: The bindings, or None if the file cannot be read or is invalid.
    """
    try:
        return load_bindings(path)
    except BindingsError as exc:
        print(f"{path}: invalid 1-Wire bindings:", file=sys.stderr)
        for violation in exc.violations:
            print(f"  {violation}", file=sys.stderr)
    except OSError as exc:
        print(f"cannot read bindings file {path}: {exc}", file=sys.stderr)
    return None


def _scan_family(rom: int) -> str:
    """Name the 1-Wire family of a ROM for ``onewire scan``.

    :param rom: 64-bit ROM id.
    :returns: ``DS18B20``, ``DS2438`` or ``unknown 0xNN``.
    """
    family = rom_family(rom)
    if family == FAMILY_DS18B20:
        return "DS18B20"
    if family == FAMILY_DS2438:
        return "DS2438"
    return f"unknown 0x{family:02X}"


def _scan_reading(reading: SlotReading) -> str:
    """Format a slot's reading(s), or ``---`` when it is not usable.

    Usability follows the monitor/LCD rule (unknown status bits make a slot unusable).

    :param reading: A present slot.
    :returns: e.g. ``21.50 degC`` or ``22.10 degC  3300 mV``.
    """
    family = rom_family(reading.rom)
    if family not in (FAMILY_DS18B20, FAMILY_DS2438) or _slot_unusable_cause(reading):
        return "---"
    text = f"{reading.primary / 100:.2f} degC"
    if family == FAMILY_DS2438:
        text += f"  {reading.secondary} mV"
    return text


def yaml_stub(rom: int) -> str:
    """Bindings-file entry to paste for an unbound ROM; the ROM is always quoted.

    Quoting keeps an all-digit ROM a string (YAML would otherwise read a number).

    :param rom: 64-bit ROM id.
    :returns: Three lines: ``- rom: "..."``, ``  role: TODO``, ``  label: TODO``.
    """
    return f'- rom: "{format_rom(rom)}"\n  role: TODO\n  label: TODO'


def _read_snapshot_or_report(
    parser: argparse.ArgumentParser, args: argparse.Namespace
) -> reg.Snapshot | int:
    """Read one snapshot, mapping a failure to an exit status.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: The snapshot, or the exit status after printing the failure.
    """
    client = _open_client(parser, args)
    try:
        with client:
            return client.read_snapshot()
    except CommsError as exc:
        print(f"communication failure: {exc}", file=sys.stderr)
        return EXIT_COMMS
    except ModbusExceptionError as exc:
        print(f"modbus exception: {exc}", file=sys.stderr)
        return EXIT_MODBUS


def _cmd_onewire_scan(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """List a node's present 1-Wire devices with their bindings (reads the snapshot only).

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    path: Path = args.bindings
    if path.exists():
        loaded = _load_bindings_or_report(path)
        if loaded is None:
            return EXIT_FAIL
        bindings = {b.rom: b for b in loaded}
    else:
        print(f"bindings file {path} not found; treating every device as unbound")
        bindings = {}
    snap = _read_snapshot_or_report(parser, args)
    if isinstance(snap, int):
        return snap
    present = [s for s in decode_slots(snap) if s.status & SlotStatus.PRESENT]
    if not present:
        print(f"unit {args.unit_id}: no 1-Wire devices present")
        return EXIT_OK
    print(f"{'rom':<18}{'family':<13}{'reading':<22}binding")
    unbound: list[int] = []
    for slot in present:
        binding = bindings.get(slot.rom)
        if binding is None:
            unbound.append(slot.rom)
            bound = "UNBOUND"
        else:
            bound = f"{binding.role}  {binding.label!r}"
        print(
            f"{format_rom(slot.rom):<18}{_scan_family(slot.rom):<13}"
            f"{_scan_reading(slot):<22}{bound}"
        )
    if unbound:
        print()
        print(f"# {len(unbound)} unbound device(s): paste under 'devices:', fill role and label")
        for rom in unbound:
            print(yaml_stub(rom))
    return EXIT_OK


def _cmd_onewire_validate(args: argparse.Namespace) -> int:
    """Validate a bindings file.

    :param args: Parsed arguments.
    :returns: Exit status.
    """
    bindings = _load_bindings_or_report(args.bindings)
    if bindings is None:
        return EXIT_FAIL
    print(f"OK: {len(bindings)} 1-Wire device(s) in {args.bindings}")
    return EXIT_OK


def _cmd_onewire_push(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Write a node's name table from the bindings file and verify it by read-back.

    The bindings are loaded and validated before any connection is opened.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status (:data:`EXIT_NAMES_UNSUPPORTED` if the node has no name table).
    """
    path: Path = args.bindings
    bindings = _load_bindings_or_report(path)
    if bindings is None:
        return EXIT_FAIL
    try:
        revision = bindings_revision(path)
    except OSError as exc:
        print(f"cannot read bindings file {path}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    client = _open_client(parser, args)
    try:
        with client:
            entries = select_for_node(bindings, decode_slots(client.read_snapshot()))
            client.write_name_table(entries, revision)
            back = client.read_name_table()
    except CommsError as exc:
        print(f"communication failure: {exc}", file=sys.stderr)
        return EXIT_COMMS
    except ModbusExceptionError as exc:
        if exc.code == _ILLEGAL_DATA_ADDRESS:
            print("node does not support names (protocol 1.3?)", file=sys.stderr)
            return EXIT_NAMES_UNSUPPORTED
        print(f"modbus exception: {exc}", file=sys.stderr)
        return EXIT_MODBUS
    expected: tuple[int, tuple[NameEntry, ...]] = (revision, entries)
    if back != expected:
        print(f"read-back mismatch: wrote {expected!r}, read back {back!r}", file=sys.stderr)
        return EXIT_FAIL
    logger.debug("unit {}: name table revision 0x{:04X} verified", args.unit_id, revision)
    print(f"unit {args.unit_id}: pushed {len(entries)} name(s), revision 0x{revision:04X}")
    for entry in entries:
        print(f"  {entry.label:<{LABEL_MAX_CHARS}} -> {format_rom(entry.rom)}")
    return EXIT_OK


def _cmd_onewire(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """Dispatch the ``onewire`` sub-commands.

    :param parser: Parser for usage errors.
    :param args: Parsed arguments.
    :returns: Exit status.
    """
    if args.onewire_command == "scan":
        return _cmd_onewire_scan(parser, args)
    if args.onewire_command == "validate":
        return _cmd_onewire_validate(args)
    return _cmd_onewire_push(parser, args)


def _cmd_bringup(args: argparse.Namespace) -> int:
    """Run the bring-up probe capture, or the read-only pre-erase esptool reads.

    :param args: Parsed arguments.
    :returns: Exit status: 0 on a complete report (or all pre-erase commands run),
        1 on a partial capture, 2 on a serial error.
    """
    if args.pre_erase:
        bringup_capture.run_pre_erase(args.port, args.logs)
        return EXIT_OK
    try:
        _, _, log = bringup_capture.capture(
            args.port,
            args.logs,
            timeout_s=args.timeout,
            reset=not args.no_reset,
            request_report=args.no_reset,
        )
    except OSError as exc:
        logger.error("serial port {}: {}", args.port, exc)
        return EXIT_COMMS
    return EXIT_OK if log.complete else EXIT_FAIL


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    :param argv: Arguments without the program name; ``sys.argv[1:]`` if None.
    :returns: Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    logger.remove()
    logger.add(sys.stderr, level="DEBUG" if args.verbose else "INFO")
    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "sim":
            return _cmd_sim(parser, args)
        if args.command == "read":
            return _cmd_read(parser, args)
        if args.command == "onewire":
            return _cmd_onewire(parser, args)
        if args.command == "bringup":
            return _cmd_bringup(args)
        return _cmd_publish_status(parser, args)
    finally:
        logger.remove()
