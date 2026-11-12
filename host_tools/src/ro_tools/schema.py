"""Typed model and validator for ``protocol/register_map.yaml``.

The YAML file is the normative register contract. :func:`load` reads it into
a frozen :class:`RegisterMap`; :func:`parse` rejects any malformed map by
raising :class:`SchemaError` carrying every violation found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MAP_PATH: Path = Path(__file__).resolve().parents[3] / "protocol" / "register_map.yaml"

REQUIRED_TOP_LEVEL: tuple[str, ...] = (
    "protocol",
    "version",
    "unit_id",
    "serial",
    "addressing",
    "word_order_32bit",
    "byte_order_per_word",
    "polling",
    "validity_bits",
    "critical_validity_bits",
    "status_bits",
    "fault_bits",
    "input_registers",
    "holding_registers",
    "controller_status_extension",
    "enums",
    "controller_flags_bits",
    "fault_codes",
)

_TYPE_WORDS: dict[str, int] = {"u16": 1, "i16": 1, "u32": 2, "i32": 2}
_ACCESS: frozenset[str] = frozenset({"read_only", "write_multiple_only"})
_FAULT_SOURCES: frozenset[str] = frozenset({"controller", "sensor"})
_SCALE_SUFFIX = re.compile(r"_x(10|100|1000)$")
_BIT_TABLES: tuple[str, ...] = (
    "validity_bits",
    "status_bits",
    "fault_bits",
    "controller_flags_bits",
)


class SchemaError(Exception):
    """Raised when the register map violates the schema.

    :ivar violations: Every violation found, one human-readable string each.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations: list[str] = list(violations)
        super().__init__(
            f"{len(self.violations)} register map violation(s):\n  - "
            + "\n  - ".join(self.violations)
        )


@dataclass(frozen=True)
class Register:
    """One register-map entry."""

    address: int
    name: str
    type: str
    words: int
    scale_divisor: int
    unit: str | None
    access: str
    enum: str | None
    equals: int | None

    @property
    def reserved(self) -> bool:
        """Whether this register is a reserved placeholder."""
        return self.name.startswith("reserved_")


@dataclass(frozen=True)
class FaultCode:
    """One entry of the fault-code catalog."""

    code: int
    source: str
    default_severity: str
    description: str
    state_dependent: bool


@dataclass(frozen=True)
class RegisterMap:
    """The validated, immutable register map."""

    version_major: int
    version_minor: int
    unit_id: int
    baud: int
    data_bits: int
    parity: str
    stop_bits: int
    input_start: int
    input_count: int
    period_ms: int
    critical_max_age_ms: int
    client_loss_timeout_ms: int
    validity_bits: dict[int, str]
    critical_validity_bits: tuple[int, ...]
    status_bits: dict[int, str]
    fault_bits: dict[int, str]
    controller_flags_bits: dict[int, str]
    input_registers: tuple[Register, ...]
    holding_registers: tuple[Register, ...]
    status_start: int
    status_count: int
    status_timeout_ms: int
    status_schema_major: int
    enums: dict[str, dict[int, str]]
    fault_codes: tuple[FaultCode, ...]


def _is_int(value: Any) -> bool:
    """Return True for real integers (``bool`` is rejected).

    :param value: Value to test.
    :returns: Whether ``value`` is an ``int`` and not a ``bool``.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _section(raw: dict, key: str, keys: tuple[str, ...], bad: list[str]) -> dict:
    """Return ``raw[key]`` as a mapping, recording missing sub-keys.

    :param raw: Parsed YAML document.
    :param key: Top-level key naming a mapping section.
    :param keys: Sub-keys that must be present.
    :param bad: Violation list to append to.
    :returns: The section, or an empty dict if it is not a mapping.
    """
    sec = raw[key]
    if not isinstance(sec, dict):
        bad.append(f"{key}: must be a mapping")
        return {}
    for sub in keys:
        if sub not in sec:
            bad.append(f"{key}.{sub}: missing")
    return sec


def _int_field(sec: dict, section: str, key: str, bad: list[str]) -> int:
    """Fetch an integer field, recording a violation if absent or non-int.

    :param sec: Mapping holding the field.
    :param section: Section name used in messages.
    :param key: Field name.
    :param bad: Violation list to append to.
    :returns: The value, or 0 when invalid (a violation is then recorded).
    """
    value = sec.get(key)
    if key in sec and not _is_int(value):
        bad.append(f"{section}.{key}: must be an integer, got {value!r}")
        return 0
    return value if _is_int(value) else 0


def _parse_bits(raw: dict, table: str, bad: list[str]) -> dict[int, str]:
    """Validate and return a bit-name table (rule 7).

    :param raw: Parsed YAML document.
    :param table: Name of the bit table.
    :param bad: Violation list to append to.
    :returns: Mapping of bit index to name.
    """
    src = raw[table]
    if not isinstance(src, dict):
        bad.append(f"{table}: must be a mapping")
        return {}
    out: dict[int, str] = {}
    for bit, name in src.items():
        if not _is_int(bit) or not 0 <= bit <= 15:
            bad.append(f"{table}: bit index {bit!r} must be an integer in 0..15")
            continue
        out[bit] = str(name)
    return out


def _parse_enums(raw: dict, bad: list[str]) -> dict[str, dict[int, str]]:
    """Validate and return the enum tables (rule 10, value half).

    :param raw: Parsed YAML document.
    :param bad: Violation list to append to.
    :returns: Mapping of enum name to ``{value: member_name}``.
    """
    src = raw["enums"]
    if not isinstance(src, dict):
        bad.append("enums: must be a mapping")
        return {}
    out: dict[str, dict[int, str]] = {}
    for ename, members in src.items():
        if not isinstance(members, dict):
            bad.append(f"enums.{ename}: must be a mapping")
            continue
        table: dict[int, str] = {}
        seen: set[str] = set()
        for value, member in members.items():
            if not _is_int(value) or not 0 <= value <= 65535:
                bad.append(f"enums.{ename}: value {value!r} must be an integer in 0..65535")
                continue
            if str(member) in seen:
                bad.append(f"enums.{ename}: duplicate member name {member!r}")
            seen.add(str(member))
            table[value] = str(member)
        out[str(ename)] = table
    return out


def _parse_register(
    entry: Any, table: str, enums: dict[str, dict[int, str]], bad: list[str]
) -> Register | None:
    """Validate one register entry (rules 2, 5, 9, 10) and build it.

    :param entry: Raw register mapping.
    :param table: Table name, for messages.
    :param enums: Validated enum tables.
    :param bad: Violation list to append to.
    :returns: The register, or None if it is too malformed to build.
    """
    if not isinstance(entry, dict):
        bad.append(f"{table}: entry {entry!r} must be a mapping")
        return None
    name = entry.get("name")
    where = f"{table}.{name}"
    ok = True
    if not isinstance(name, str):
        bad.append(f"{table}: entry {entry!r} has no string 'name'")
        return None
    address = entry.get("address")
    if not _is_int(address) or address < 0:
        bad.append(f"{where}: address must be a non-negative integer, got {address!r}")
        ok = False
    rtype = entry.get("type")
    words = entry.get("words", 1)
    if rtype not in _TYPE_WORDS:
        bad.append(f"{where}: type {rtype!r} not in {sorted(_TYPE_WORDS)}")
        ok = False
    elif words != _TYPE_WORDS[rtype] or not _is_int(words):
        bad.append(f"{where}: words {words!r} does not match type {rtype} ({_TYPE_WORDS[rtype]})")
        ok = False
    divisor = entry.get("scale_divisor", 1)
    if not _is_int(divisor) or divisor < 1:
        bad.append(f"{where}: scale_divisor must be an integer >= 1, got {divisor!r}")
        ok = False
    else:
        suffix = _SCALE_SUFFIX.search(name)
        expected = int(suffix.group(1)) if suffix else 1
        if divisor != expected:
            bad.append(f"{where}: scale_divisor {divisor} must be {expected} given the name")
            ok = False
    access = entry.get("access")
    if access not in _ACCESS:
        bad.append(f"{where}: access {access!r} not in {sorted(_ACCESS)}")
        ok = False
    enum = entry.get("enum")
    if enum is not None and enum not in enums:
        bad.append(f"{where}: enum {enum!r} is not defined in enums")
        ok = False
    equals = entry.get("equals")
    if equals is not None and not _is_int(equals):
        bad.append(f"{where}: equals must be an integer, got {equals!r}")
        ok = False
    if not ok:
        return None
    return Register(
        address=address,
        name=name,
        type=rtype,
        words=words,
        scale_divisor=divisor,
        unit=entry.get("unit"),
        access=access,
        enum=enum,
        equals=equals,
    )


def _occupied(regs: list[Register], table: str, bad: list[str]) -> set[int]:
    """Return occupied addresses, flagging overlaps (rule 3).

    :param regs: Registers of one table.
    :param table: Table name, for messages.
    :param bad: Violation list to append to.
    :returns: The set of addresses occupied.
    """
    owner: dict[int, str] = {}
    for reg in regs:
        for addr in range(reg.address, reg.address + reg.words):
            if addr in owner:
                bad.append(f"{table}.{reg.name}: address {addr} already occupied by {owner[addr]}")
            else:
                owner[addr] = reg.name
    return set(owner)


def _parse_faults(raw: dict, severities: dict[int, str], bad: list[str]) -> tuple[FaultCode, ...]:
    """Validate and return the fault-code catalog (rule 11).

    :param raw: Parsed YAML document.
    :param severities: The ``fault_severity`` enum table.
    :param bad: Violation list to append to.
    :returns: Fault codes sorted by code.
    """
    src = raw["fault_codes"]
    if not isinstance(src, list):
        bad.append("fault_codes: must be a list")
        return ()
    names = set(severities.values())
    out: dict[int, FaultCode] = {}
    for entry in src:
        if not isinstance(entry, dict):
            bad.append(f"fault_codes: entry {entry!r} must be a mapping")
            continue
        code = entry.get("code")
        where = f"fault_codes[{code}]"
        if not _is_int(code) or not 0 <= code <= 65535:
            bad.append(f"fault_codes: code {code!r} must be an integer in 0..65535")
            continue
        ok = True
        if code in out:
            bad.append(f"{where}: duplicate code")
            ok = False
        source = entry.get("source")
        if source not in _FAULT_SOURCES:
            bad.append(f"{where}: source {source!r} not in {sorted(_FAULT_SOURCES)}")
            ok = False
        severity = entry.get("default_severity")
        if severity not in names:
            bad.append(f"{where}: default_severity {severity!r} not in fault_severity enum")
            ok = False
        if ok:
            out[code] = FaultCode(
                code=code,
                source=source,
                default_severity=severity,
                description=str(entry.get("description", "")),
                state_dependent=bool(entry.get("state_dependent", False)),
            )
    if 0 not in out and not any(isinstance(e, dict) and e.get("code") == 0 for e in src):
        bad.append("fault_codes: code 0 (no active fault) is required")
    elif 0 in out and out[0].default_severity != "none":
        bad.append("fault_codes[0]: default_severity must be 'none'")
    return tuple(out[c] for c in sorted(out))


def parse(raw: dict) -> RegisterMap:
    """Validate a parsed register-map document and build the model.

    :param raw: Result of ``yaml.safe_load`` on the register map.
    :returns: The validated, immutable :class:`RegisterMap`.
    :raises SchemaError: If any rule is violated; all violations are reported.
    """
    if not isinstance(raw, dict):
        raise SchemaError(["document root must be a mapping"])
    missing = [f"{k}: required top-level key missing" for k in REQUIRED_TOP_LEVEL if k not in raw]
    if missing:
        raise SchemaError(missing)

    bad: list[str] = []
    for key, expected in (
        ("addressing", "zero_based_pdu_offset"),
        ("word_order_32bit", "high_word_first"),
        ("byte_order_per_word", "big_endian"),
    ):
        if raw[key] != expected:
            bad.append(f"{key}: must be {expected!r}, got {raw[key]!r}")

    version = _section(raw, "version", ("major", "minor"), bad)
    serial = _section(raw, "serial", ("baud", "data_bits", "parity", "stop_bits"), bad)
    polling = _section(
        raw,
        "polling",
        (
            "input_start",
            "input_count",
            "period_ms",
            "critical_max_age_ms",
            "client_loss_timeout_ms",
        ),
        bad,
    )
    ext = _section(
        raw,
        "controller_status_extension",
        ("start", "count", "timeout_ms", "status_schema_major"),
        bad,
    )
    if not _is_int(raw["unit_id"]):
        bad.append(f"unit_id: must be an integer, got {raw['unit_id']!r}")

    bits = {t: _parse_bits(raw, t, bad) for t in _BIT_TABLES}
    critical = raw["critical_validity_bits"]
    if not isinstance(critical, list):
        bad.append("critical_validity_bits: must be a list")
        critical = []
    for bit in critical:
        if bit not in bits["validity_bits"]:
            bad.append(f"critical_validity_bits: bit {bit!r} is not a key of validity_bits")

    enums = _parse_enums(raw, bad)

    tables: dict[str, list[Register]] = {}
    for table in ("input_registers", "holding_registers"):
        entries = raw[table]
        if not isinstance(entries, list):
            bad.append(f"{table}: must be a list")
            tables[table] = []
            continue
        built = [_parse_register(e, table, enums, bad) for e in entries]
        tables[table] = [r for r in built if r is not None]

    seen_names: set[str] = set()
    for reg in tables["input_registers"] + tables["holding_registers"]:
        if reg.name in seen_names:
            bad.append(f"{reg.name}: register name is not unique across tables")
        seen_names.add(reg.name)
        if not reg.name.isidentifier():
            bad.append(f"{reg.name}: register name is not a valid identifier")

    occupied_in = _occupied(tables["input_registers"], "input_registers", bad)
    _occupied(tables["holding_registers"], "holding_registers", bad)

    input_start = _int_field(polling, "polling", "input_start", bad)
    input_count = _int_field(polling, "polling", "input_count", bad)
    if occupied_in != set(range(input_start, input_start + input_count)):
        bad.append(
            "input_registers: occupied addresses must equal polling window "
            f"{input_start}..{input_start + input_count - 1}"
        )

    status_start = _int_field(ext, "controller_status_extension", "start", bad)
    status_count = _int_field(ext, "controller_status_extension", "count", bad)
    write_addrs = {
        a
        for r in tables["holding_registers"]
        if r.access == "write_multiple_only"
        for a in range(r.address, r.address + r.words)
    }
    if write_addrs != set(range(status_start, status_start + status_count)):
        bad.append(
            "holding_registers: write_multiple_only addresses must equal "
            f"controller_status_extension {status_start}..{status_start + status_count - 1}"
        )

    fault_codes = _parse_faults(raw, enums.get("fault_severity", {}), bad)
    if "fault_severity" not in enums:
        bad.append("enums.fault_severity: required")

    ints = {
        "version_major": _int_field(version, "version", "major", bad),
        "version_minor": _int_field(version, "version", "minor", bad),
        "baud": _int_field(serial, "serial", "baud", bad),
        "data_bits": _int_field(serial, "serial", "data_bits", bad),
        "stop_bits": _int_field(serial, "serial", "stop_bits", bad),
        "period_ms": _int_field(polling, "polling", "period_ms", bad),
        "critical_max_age_ms": _int_field(polling, "polling", "critical_max_age_ms", bad),
        "client_loss_timeout_ms": _int_field(polling, "polling", "client_loss_timeout_ms", bad),
        "status_timeout_ms": _int_field(ext, "controller_status_extension", "timeout_ms", bad),
        "status_schema_major": _int_field(
            ext, "controller_status_extension", "status_schema_major", bad
        ),
    }
    if bad:
        raise SchemaError(bad)

    return RegisterMap(
        unit_id=raw["unit_id"],
        parity=str(serial["parity"]),
        input_start=input_start,
        input_count=input_count,
        validity_bits=bits["validity_bits"],
        critical_validity_bits=tuple(critical),
        status_bits=bits["status_bits"],
        fault_bits=bits["fault_bits"],
        controller_flags_bits=bits["controller_flags_bits"],
        input_registers=tuple(sorted(tables["input_registers"], key=lambda r: r.address)),
        holding_registers=tuple(sorted(tables["holding_registers"], key=lambda r: r.address)),
        status_start=status_start,
        status_count=status_count,
        enums=enums,
        fault_codes=fault_codes,
        **ints,
    )


def load(path: Path = DEFAULT_MAP_PATH) -> RegisterMap:
    """Read and validate a register-map YAML file.

    :param path: Location of the YAML file.
    :returns: The validated :class:`RegisterMap`.
    :raises SchemaError: If the map violates the schema.
    :raises OSError: If the file cannot be read.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return parse(raw)
