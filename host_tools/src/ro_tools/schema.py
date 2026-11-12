"""Typed model and validator for ``protocol/register_map.yaml``.

The YAML file is the normative register contract. :func:`load` reads it into
a frozen :class:`RegisterMap`; :func:`parse` rejects any malformed map by
raising :class:`SchemaError` carrying every violation found.
"""

from __future__ import annotations

import keyword
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
    status_require_sequence_progress: bool
    enums: dict[str, dict[int, str]]
    fault_codes: tuple[FaultCode, ...]


def _is_int(value: Any) -> bool:
    """Return True for real integers (``bool`` is rejected).

    :param value: Value to test.
    :returns: Whether ``value`` is an ``int`` and not a ``bool``.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def _is_name(value: Any) -> bool:
    """Return True for a string usable as a Python identifier and not a keyword.

    :param value: Value to test.
    :returns: Whether ``value`` is an identifier that is neither a hard nor a
        soft keyword.
    """
    return (
        isinstance(value, str)
        and value.isidentifier()
        and not keyword.iskeyword(value)
        and not keyword.issoftkeyword(value)
    )


def camel_case(name: str) -> str:
    """Convert a snake_case name to CamelCase (the generated class name).

    :param name: Snake-case identifier.
    :returns: CamelCase identifier.
    """
    return "".join(part.capitalize() for part in name.split("_"))


def _member_problem(name: Any) -> str | None:
    """Explain why ``name`` cannot become an upper-cased class member.

    :param name: Candidate enum-member or bit name from the YAML.
    :returns: A reason, or None when the upper-cased name is a usable member.
    """
    if not isinstance(name, str):
        return f"{name!r} must be a string"
    if not name.isidentifier():
        return f"{name!r} is not an identifier"
    upper = name.upper()
    if not upper.isidentifier() or keyword.iskeyword(upper) or keyword.issoftkeyword(upper):
        return f"{name!r} upper-cases to {upper!r}, which is not a usable member name"
    if upper.startswith("_"):
        return f"{name!r} must not start with an underscore"
    return None


def _check_member_names(where: str, names: list[Any], bad: list[str]) -> None:
    """Record unusable and case-colliding generated member names.

    :param where: Table description for messages.
    :param names: Member names in table order.
    :param bad: Violation list to append to.
    """
    owner: dict[str, str] = {}
    for name in names:
        problem = _member_problem(name)
        if problem:
            bad.append(f"{where}: member name {problem}")
        elif name.upper() in owner:
            bad.append(
                f"{where}: member names {owner[name.upper()]!r} and {name!r} "
                f"both upper-case to {name.upper()!r}"
            )
        else:
            owner[name.upper()] = name


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
        out[bit] = name
    _check_member_names(table, list(out.values()), bad)
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
    classes: dict[str, str] = {}
    for ename, members in src.items():
        if not _is_name(ename) or not _is_name(camel_case(ename)):
            bad.append(f"enums: name {ename!r} cannot become a generated class name")
        elif camel_case(ename) in classes:
            bad.append(f"enums: {classes[camel_case(ename)]!r} and {ename!r} generate one class")
        else:
            classes[camel_case(ename)] = ename
        if not isinstance(members, dict):
            bad.append(f"enums.{ename}: must be a mapping")
            continue
        table: dict[int, str] = {}
        for value, member in members.items():
            if not _is_int(value) or not 0 <= value <= 65535:
                bad.append(f"enums.{ename}: value {value!r} must be an integer in 0..65535")
                continue
            table[value] = member
        _check_member_names(f"enums.{ename}", list(table.values()), bad)
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
    if not isinstance(rtype, str) or rtype not in _TYPE_WORDS:
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
    if not isinstance(access, str) or access not in _ACCESS:
        bad.append(f"{where}: access {access!r} not in {sorted(_ACCESS)}")
        ok = False
    enum = entry.get("enum")
    if enum is not None and (not isinstance(enum, str) or enum not in enums):
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
    # Malformed members are already recorded as violations by _parse_enums.
    names = {name for name in severities.values() if isinstance(name, str)}
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
        if not isinstance(source, str) or source not in _FAULT_SOURCES:
            bad.append(f"{where}: source {source!r} not in {sorted(_FAULT_SOURCES)}")
            ok = False
        severity = entry.get("default_severity")
        if not isinstance(severity, str) or severity not in names:
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


def _check_status_extension(ext: dict, holding: list[Register], bad: list[str]) -> bool:
    """Validate the fixed properties of the controller status extension.

    :param ext: The ``controller_status_extension`` section.
    :param holding: Parsed holding registers.
    :param bad: Violation list to append to.
    :returns: The value of ``require_sequence_progress`` (False when invalid).
    """
    where = "controller_status_extension"
    for key, expected in (
        ("function_code_write", 16),
        ("write_mode", "atomic_full_block_only"),
    ):
        if key in ext and (ext[key] != expected or isinstance(ext[key], bool)):
            bad.append(f"{where}.{key}: must be {expected!r}, got {ext[key]!r}")
    if "display_only" in ext and ext["display_only"] is not True:
        bad.append(f"{where}.display_only: must be true, got {ext['display_only']!r}")
    progress = ext.get("require_sequence_progress")
    if "require_sequence_progress" in ext and not isinstance(progress, bool):
        bad.append(f"{where}.require_sequence_progress: must be a boolean, got {progress!r}")
    schema_reg = next((r for r in holding if r.name == "status_schema_major"), None)
    declared = ext.get("status_schema_major")
    if schema_reg is None:
        bad.append("holding_registers: status_schema_major register is required")
    elif _is_int(declared) and schema_reg.equals != declared:
        bad.append(
            f"holding_registers.status_schema_major: equals {schema_reg.equals!r} "
            f"must match {where}.status_schema_major {declared!r}"
        )
    return progress is True


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
        (
            "start",
            "count",
            "timeout_ms",
            "status_schema_major",
            "function_code_write",
            "write_mode",
            "display_only",
            "require_sequence_progress",
        ),
        bad,
    )
    if not _is_int(raw["unit_id"]):
        bad.append(f"unit_id: must be an integer, got {raw['unit_id']!r}")

    bits = {t: _parse_bits(raw, t, bad) for t in _BIT_TABLES}
    critical = raw["critical_validity_bits"]
    if not isinstance(critical, list):
        bad.append("critical_validity_bits: must be a list")
        critical = []
    seen_critical: set[int] = set()
    for bit in critical:
        if not _is_int(bit) or bit not in bits["validity_bits"]:
            bad.append(f"critical_validity_bits: bit {bit!r} is not a key of validity_bits")
        elif bit in seen_critical:
            bad.append(f"critical_validity_bits: duplicate bit {bit!r}")
        else:
            seen_critical.add(bit)

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
        if not _is_name(reg.name):
            bad.append(f"{reg.name}: register name is not a valid identifier or is a keyword")

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

    require_progress = _check_status_extension(ext, tables["holding_registers"], bad)

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
        status_require_sequence_progress=require_progress,
        enums=enums,
        fault_codes=fault_codes,
        **ints,
    )


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that records repeated mapping keys instead of hiding them.

    :ivar duplicates: One message per repeated key, with its line number.
    """

    def __init__(self, stream: str) -> None:
        super().__init__(stream)
        self.duplicates: list[str] = []

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict:
        """Build a mapping, noting keys that occur more than once.

        :param node: The YAML mapping node.
        :param deep: Passed through to the base constructor.
        :returns: The constructed mapping (the last duplicate still wins here;
            :func:`load` rejects the document before it is used).
        """
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
            first_line: dict[Any, int] = {}
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=True)
                try:
                    hash(key)
                except TypeError:
                    continue  # the base constructor reports unhashable keys
                line = key_node.start_mark.line + 1
                if key in first_line:
                    self.duplicates.append(
                        f"duplicate key {key!r} at line {line} "
                        f"(first used at line {first_line[key]})"
                    )
                else:
                    first_line[key] = line
        return super().construct_mapping(node, deep)


def load(path: Path = DEFAULT_MAP_PATH) -> RegisterMap:
    """Read and validate a register-map YAML file.

    :param path: Location of the YAML file.
    :returns: The validated :class:`RegisterMap`.
    :raises SchemaError: If the map violates the schema.
    :raises OSError: If the file cannot be read.
    """
    loader = _UniqueKeyLoader(Path(path).read_text(encoding="utf-8"))
    try:
        raw = loader.get_single_data()
    finally:
        loader.dispose()
    if loader.duplicates:
        raise SchemaError(loader.duplicates)
    return parse(raw)
