"""Render the validated register map to ``registers.py`` and ``ro_registers.hpp``.

``python -m ro_tools.codegen`` regenerates the committed Python module and the
firmware's C++ header. The output depends on the standard library only and is
byte-for-byte deterministic.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import reduce
from operator import or_
from pathlib import Path

from ro_tools import schema
from ro_tools.schema import Register, RegisterMap

GENERATED_PATH: Path = Path(__file__).resolve().parent / "generated" / "registers.py"
CPP_PATH: Path = (
    Path(__file__).resolve().parents[3] / "firmware/lib/ro_protocol/src/ro_registers.hpp"
)

_CPP_TYPES: dict[str, str] = {
    "u16": "std::uint16_t",
    "i16": "std::int16_t",
    "u32": "std::uint32_t",
    "i32": "std::int32_t",
}

_PARITY: dict[str, str] = {"even": "E", "odd": "O", "none": "N"}
# Fixed name-table geometry; schema.py validates count against these.
_NAMES_HEADER_WORDS = 3
_NAMES_ROM_WORDS = 4
_REQUIRED_STATUS_FIELDS: tuple[str, ...] = (
    "controller_fault_code",
    "controller_fault_severity",
    "controller_fault_count",
    "controller_flags",
)
_FLAG_CLASSES: tuple[tuple[str, str, str], ...] = (
    ("ValidityBits", "validity_bits", "Bits of the validity mask register."),
    ("StatusBits", "status_bits", "Bits of the module status register."),
    ("FaultBits", "fault_bits", "Bits of the fault mask register."),
    ("ControllerFlags", "controller_flags_bits", "Bits of the controller flags register."),
)
_TYPE_RANGES: tuple[tuple[str, int, int], ...] = (
    ("u16", 0, 65535),
    ("i16", -32768, 32767),
    ("u32", 0, 4294967295),
    ("i32", -2147483648, 2147483647),
)

_CODEC_BODY = '''\
def _check(name: str, typ: str, value: int) -> None:
    lo, hi = TYPE_RANGES[typ]
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise ValueError(f"{name}={value!r} out of range for {typ}")


def _encode(obj: object, layout: tuple[tuple[str, str, int], ...], count: int) -> list[int]:
    words = [0] * count
    for name, typ, offset in layout:
        value = getattr(obj, name)
        _check(name, typ, value)
        if typ in ("u32", "i32"):
            value &= 0xFFFFFFFF
            words[offset] = value >> 16
            words[offset + 1] = value & 0xFFFF
        else:
            words[offset] = value & 0xFFFF
    return words


def _decode(words: Sequence[int], layout: tuple[tuple[str, str, int], ...], count: int) -> dict[str, int]:
    if len(words) != count:
        raise ValueError(f"expected {count} words, got {len(words)}")
    for w in words:
        _check("word", "u16", w)
    out: dict[str, int] = {}
    for name, typ, offset in layout:
        if typ in ("u32", "i32"):
            value = (words[offset] << 16) | words[offset + 1]
            if typ == "i32" and value >= 0x80000000:
                value -= 0x100000000
        else:
            value = words[offset]
            if typ == "i16" and value >= 0x8000:
                value -= 0x10000
        out[name] = value
    return out


def encode_snapshot(s: Snapshot) -> list[int]:
    """Encode a snapshot to INPUT_COUNT register words; reserved words are zero."""
    return _encode(s, SNAPSHOT_LAYOUT, INPUT_COUNT)


def decode_snapshot(words: Sequence[int]) -> Snapshot:
    """Decode INPUT_COUNT register words. Makes no validity or freshness judgement."""
    return Snapshot(**_decode(words, SNAPSHOT_LAYOUT, INPUT_COUNT))


def encode_status(s: ControllerStatus) -> list[int]:
    """Encode a controller status block to STATUS_COUNT register words."""
    return _encode(s, STATUS_LAYOUT, STATUS_COUNT)


def decode_status(words: Sequence[int]) -> ControllerStatus:
    """Decode STATUS_COUNT register words without validating field values."""
    return ControllerStatus(**_decode(words, STATUS_LAYOUT, STATUS_COUNT))


def validate_status(words: Sequence[int]) -> None:
    """Raise StatusValidationError unless words form an acceptable status block."""
    try:
        s = decode_status(words)
    except ValueError as exc:
        raise StatusValidationError(str(exc)) from exc
    for name, allowed in _STATUS_ALLOWED:
        if getattr(s, name) not in allowed:
            raise StatusValidationError(f"{name}={getattr(s, name)} not permitted")
    if s.controller_flags & ~CONTROLLER_FLAGS_DEFINED_MASK:
        raise StatusValidationError("reserved controller_flags bit set")
    none = (s.controller_fault_code == 0, s.controller_fault_severity == 0, s.controller_fault_count == 0)
    if any(none) and not all(none):
        raise StatusValidationError("fault code, severity and count are inconsistent")
'''


def _camel(name: str) -> str:
    """Convert a snake_case name to CamelCase.

    :param name: Snake-case identifier.
    :returns: CamelCase identifier.
    """
    return schema.camel_case(name)


def _bit_mask(bits: Iterable[int]) -> int:
    """Combine bit indices into a mask with bitwise OR.

    A repeated index sets the same bit again instead of carrying into the next.

    :param bits: Bit indices.
    :returns: The mask.
    """
    return reduce(or_, (1 << b for b in bits), 0)


def _layout(regs: list[Register], base: int) -> list[tuple[str, str, int]]:
    """Build layout tuples for the non-reserved registers of a table.

    :param regs: Registers of one table, sorted by address.
    :param base: Address that offsets are measured from.
    :returns: ``(name, type, word offset)`` entries.
    """
    return [(r.name, r.type, r.address - base) for r in regs if not r.reserved]


def _emit_layout(const: str, entries: list[tuple[str, str, int]]) -> list[str]:
    """Emit a layout constant.

    :param const: Name of the constant.
    :param entries: Layout entries.
    :returns: Source lines.
    """
    lines = [f"{const}: tuple[tuple[str, str, int], ...] = ("]
    lines += [f"    ({n!r}, {t!r}, {o})," for n, t, o in entries]
    lines.append(")")
    return lines


def _emit_flag(cls: str, doc: str, bits: dict[int, str]) -> list[str]:
    """Emit an ``IntFlag`` class.

    :param cls: Class name.
    :param doc: Class docstring.
    :param bits: Mapping of bit index to member name.
    :returns: Source lines.
    """
    lines = [f"class {cls}(IntFlag):", f'    """{doc}"""', ""]
    if bits:
        lines += [f"    {bits[b].upper()} = 1 << {b}" for b in sorted(bits)]
    else:
        # A memberless IntFlag cannot be instantiated, even with 0.
        lines.append("    NONE = 0")
    return lines


def _emit_dataclass_fields(regs: list[Register]) -> list[str]:
    """Emit dataclass field lines with a zero default, one integer per register.

    :param regs: Non-reserved registers in order.
    :returns: Source lines.
    """
    return [f"    {r.name}: int = 0" for r in regs]


def _status_allowed(status: list[Register], m: RegisterMap) -> list[str]:
    """Emit the ``_STATUS_ALLOWED`` table.

    :param status: Status-block registers.
    :param m: The register map.
    :returns: Source lines.
    """
    lines = ["_STATUS_ALLOWED: tuple[tuple[str, frozenset[int]], ...] = ("]
    for r in status:
        if r.equals is not None:
            allowed = [r.equals]
        elif r.enum is not None:
            allowed = sorted(m.enums[r.enum])
        else:
            continue
        lines.append(f"    ({r.name!r}, frozenset({{{', '.join(str(v) for v in allowed)}}})),")
    lines.append(")")
    return lines


def render(m: RegisterMap) -> str:
    """Render the register map as the text of the generated module.

    :param m: Validated register map.
    :returns: Module source, ending with exactly one newline.
    :raises ValueError: If the status block lacks a field the fixed
        ``validate_status`` body references.
    """
    holding = list(m.holding_registers)
    meta = [r for r in holding if r.access == "read_only"]
    status_end = m.status_start + m.status_count
    status = [
        r
        for r in holding
        if r.access == "write_multiple_only" and m.status_start <= r.address < status_end
    ]
    inputs = list(m.input_registers)
    missing = [f for f in _REQUIRED_STATUS_FIELDS if f not in {r.name for r in status}]
    if missing:
        raise ValueError(f"status block lacks required field(s): {', '.join(missing)}")
    if not meta:
        raise ValueError("no read_only holding registers for metadata")
    if m.parity not in _PARITY:
        raise ValueError(f"unsupported parity {m.parity!r}")

    out: list[str] = [
        (
            '"""GENERATED by ro_tools.codegen from protocol/register_map.yaml '
            f"(protocol {m.version_major}.{m.version_minor})."
        ),
        "",
        'DO NOT EDIT. Regenerate with: uv run ro-tools generate"""',
        "",
        "from __future__ import annotations",
        "",
        "from collections.abc import Sequence",
        "from dataclasses import dataclass",
        "from enum import IntEnum, IntFlag",
        "",
        f"PROTOCOL_MAJOR = {m.version_major}",
        f"PROTOCOL_MINOR = {m.version_minor}",
        f"UNIT_ID = {m.unit_id}",
        "",
        f"SERIAL_BAUD = {m.baud}",
        f"SERIAL_DATA_BITS = {m.data_bits}",
        f"SERIAL_PARITY = {_PARITY[m.parity]!r}",
        f"SERIAL_STOP_BITS = {m.stop_bits}",
        "",
        f"INPUT_START = {m.input_start}",
        f"INPUT_COUNT = {m.input_count}",
        f"POLL_PERIOD_MS = {m.period_ms}",
        f"CRITICAL_MAX_AGE_MS = {m.critical_max_age_ms}",
        f"CLIENT_LOSS_TIMEOUT_MS = {m.client_loss_timeout_ms}",
        "",
        f"STATUS_START = {m.status_start}",
        f"STATUS_COUNT = {m.status_count}",
        f"STATUS_TIMEOUT_MS = {m.status_timeout_ms}",
        f"STATUS_SCHEMA_MAJOR = {m.status_schema_major}",
        f"STATUS_REQUIRE_SEQUENCE_PROGRESS = {m.status_require_sequence_progress!r}",
        "",
        f"NAMES_START = {m.names_start}",
        f"NAMES_COUNT = {m.names_count}",
        f"NAMES_SCHEMA_MAJOR = {m.names_schema_major}",
        f"NAMES_ENTRY_MAX = {m.names_entry_count_max}",
        f"NAMES_ROM_WORDS = {_NAMES_ROM_WORDS}",
        f"NAMES_LABEL_WORDS = {m.names_label_words}",
        f"NAMES_LABEL_MAX_CHARS = {m.names_label_max_chars}",
        f"NAMES_ENTRY_STRIDE = {_NAMES_ROM_WORDS + m.names_label_words}",
        f"NAMES_ENTRY_BASE = {m.names_start + _NAMES_HEADER_WORDS}",
        "",
        f"METADATA_START = {min(r.address for r in meta)}",
        f"METADATA_COUNT = {len(meta)}",
        "",
    ]
    out += [f"ADDR_{r.name.upper()} = {r.address}" for r in inputs + holding]
    out.append("")
    out.append("TYPE_RANGES: dict[str, tuple[int, int]] = {")
    out += [f"    {t!r}: ({lo}, {hi})," for t, lo, hi in _TYPE_RANGES]
    out += ["}", "", ""]

    for cls, table, doc in _FLAG_CLASSES:
        out += _emit_flag(cls, doc, getattr(m, table))
        out += ["", ""]
    crit_mask = _bit_mask(m.critical_validity_bits)
    flags_mask = _bit_mask(m.controller_flags_bits)
    out += [
        f"CRITICAL_VALIDITY = ValidityBits({crit_mask:#06x})",
        f"CONTROLLER_FLAGS_DEFINED_MASK = {flags_mask}",
        "",
        "",
    ]

    for ename in sorted(m.enums):
        members = m.enums[ename]
        out += [f"class {_camel(ename)}(IntEnum):", f'    """Values of the {ename} enum."""', ""]
        out += [f"    {members[v].upper()} = {v}" for v in sorted(members)]
        out += ["", ""]

    out += [
        "@dataclass(frozen=True)",
        "class FaultCodeInfo:",
        '    """One entry of the fault-code catalog."""',
        "",
        "    code: int",
        "    source: str",
        "    default_severity: FaultSeverity",
        "    description: str",
        "    state_dependent: bool",
        "",
        "",
        "FAULT_CODES: dict[int, FaultCodeInfo] = {",
    ]
    for fc in m.fault_codes:
        out.append(
            f"    {fc.code}: FaultCodeInfo({fc.code}, {fc.source!r}, "
            f"FaultSeverity.{fc.default_severity.upper()}, {fc.description!r}, "
            f"{fc.state_dependent!r}),"
        )
    out += ["}", ""]

    snap_regs = [r for r in inputs if not r.reserved]
    snap_layout = _layout(inputs, m.input_start)
    status_layout = _layout(status, m.status_start)
    meta_layout = _layout(meta, min(r.address for r in meta))
    out += _emit_layout("SNAPSHOT_LAYOUT", snap_layout) + [""]
    out += _emit_layout("STATUS_LAYOUT", status_layout) + [""]
    out += _emit_layout("METADATA_LAYOUT", meta_layout) + ["", ""]

    out += [
        "@dataclass(frozen=True)",
        "class Snapshot:",
        '    """One decoded input-register snapshot; reserved registers are omitted."""',
        "",
    ]
    out += _emit_dataclass_fields(snap_regs)
    for r in snap_regs:
        if r.scale_divisor > 1:
            base = r.name.rsplit("_x", 1)[0]
            out += [
                "",
                "    @property",
                f"    def {base}(self) -> float:",
                f'        """{r.name} scaled to engineering units."""',
                f"        return self.{r.name} / {r.scale_divisor}",
            ]
    out += ["", ""]

    out += [
        "@dataclass(frozen=True, kw_only=True)",
        "class ControllerStatus:",
        '    """Display-only controller status block written to the sensor node.',
        "",
        "    Every field is required: there is no default that could be mistaken for",
        '    a deliberate value (a zero pump_commanded would read as "off").',
        '    """',
        "",
    ]
    out += [f"    {r.name}: int" for r in status]
    out += ["", ""]
    out += [
        "class StatusValidationError(ValueError):",
        '    """Raised when a controller status block is not acceptable."""',
        "",
        "",
    ]
    out += _status_allowed(status, m) + ["", ""]
    out.append(_CODEC_BODY.rstrip("\n"))
    out += ["", "", ""]
    text = "\n".join(out).rstrip("\n") + "\n"
    return text


def write(m: RegisterMap, path: Path = GENERATED_PATH) -> None:
    """Write the generated module to ``path`` with LF newlines.

    :param m: Validated register map.
    :param path: Destination file.
    :raises ValueError: If the map cannot be rendered.
    :raises OSError: If the file cannot be written.
    """
    path.write_text(render(m), encoding="utf-8", newline="\n")


def is_current(m: RegisterMap, path: Path = GENERATED_PATH) -> bool:
    """Report whether ``path`` holds exactly the freshly rendered module.

    :param m: Validated register map.
    :param path: File to compare.
    :returns: True if the file exists and matches :func:`render`.
    """
    return path.exists() and path.read_text(encoding="utf-8") == render(m)


def _cpp_constant(name: str, value: int | str, typ: str = "std::uint16_t") -> str:
    """Emit one namespace-scope C++ constant.

    :param name: Constant name.
    :param value: Literal text or integer.
    :param typ: C++ type.
    :returns: Source line.
    """
    return f"constexpr {typ} {name} = {value};"


def _cpp_bits(namespace: str, bits: dict[int, str]) -> list[str]:
    """Emit a namespace of single-bit mask constants.

    :param namespace: Namespace name.
    :param bits: Mapping of bit index to name.
    :returns: Source lines, ending with a blank line.
    """
    lines = [f"namespace {namespace} {{"]
    lines += [_cpp_constant(bits[b].upper(), f"{1 << b:#06x}") for b in sorted(bits)]
    return lines + [f"}}  // namespace {namespace}", ""]


def _cpp_block(
    struct: str, function: str, count: str, regs: list[Register], base: int
) -> list[str]:
    """Emit a register-block struct and its encoder.

    Signed values are stored two's complement; 32-bit values are stored high
    word first. Words that no field covers (reserved registers) are zero.

    :param struct: Struct name.
    :param function: Encoder name.
    :param count: Name of the constant holding the block's word count.
    :param regs: Non-reserved registers of the block, in address order.
    :param base: Address of the first word of the block.
    :returns: Source lines, ending with a blank line.
    """
    lines = [f"struct {struct} {{"]
    lines += [f"    {_CPP_TYPES[r.type]} {r.name} = 0;" for r in regs]
    lines += [
        "};",
        "",
        f"inline void {function}(const {struct}& s, std::uint16_t (&words)[{count}]) {{",
        "    for (std::uint16_t& word : words) {",
        "        word = 0;",
        "    }",
    ]
    for r in regs:
        offset = r.address - base
        if r.type in ("u32", "i32"):
            value = f"static_cast<std::uint32_t>(s.{r.name})"
            lines.append(f"    words[{offset}] = static_cast<std::uint16_t>({value} >> 16);")
            lines.append(
                f"    words[{offset + 1}] = static_cast<std::uint16_t>({value} & 0xFFFFu);"
            )
        else:
            lines.append(f"    words[{offset}] = static_cast<std::uint16_t>(s.{r.name});")
    return lines + ["}", ""]


def render_cpp(m: RegisterMap) -> str:
    """Render the register map as the text of the firmware C++ header.

    :param m: Validated register map.
    :returns: Header source, ending with exactly one newline.
    :raises ValueError: If there is no metadata block or the parity is unsupported.
    """
    inputs = list(m.input_registers)
    meta = [r for r in m.holding_registers if r.access == "read_only"]
    if not meta:
        raise ValueError("no read_only holding registers for metadata")
    if m.parity not in _PARITY:
        raise ValueError(f"unsupported parity {m.parity!r}")
    meta_start = min(r.address for r in meta)
    out: list[str] = [
        (
            "// GENERATED by ro_tools.codegen from protocol/register_map.yaml "
            f"(protocol {m.version_major}.{m.version_minor})."
        ),
        "// DO NOT EDIT. Regenerate with: uv run ro-tools generate",
        "#pragma once",
        "",
        "#include <cstdint>",
        "",
        "namespace ro::reg {",
        "",
    ]
    constants: tuple[tuple[str, int], ...] = (
        ("PROTOCOL_MAJOR", m.version_major),
        ("PROTOCOL_MINOR", m.version_minor),
        ("UNIT_ID", m.unit_id),
        ("SERIAL_DATA_BITS", m.data_bits),
        ("SERIAL_STOP_BITS", m.stop_bits),
        ("INPUT_START", m.input_start),
        ("INPUT_COUNT", m.input_count),
        ("POLL_PERIOD_MS", m.period_ms),
        ("CRITICAL_MAX_AGE_MS", m.critical_max_age_ms),
        ("CLIENT_LOSS_TIMEOUT_MS", m.client_loss_timeout_ms),
        ("METADATA_START", meta_start),
        ("METADATA_COUNT", len(meta)),
        ("STATUS_START", m.status_start),
        ("STATUS_COUNT", m.status_count),
        ("NAMES_START", m.names_start),
        ("NAMES_COUNT", m.names_count),
    )
    out += [_cpp_constant(name, value) for name, value in constants]
    out.append(_cpp_constant("SERIAL_BAUD", m.baud, "std::uint32_t"))
    out.append(_cpp_constant("SERIAL_PARITY", repr(_PARITY[m.parity]), "char"))
    out.append("")
    out += [
        _cpp_constant(f"ADDR_{r.name.upper()}", r.address)
        for r in inputs + list(m.holding_registers)
    ]
    out.append("")
    out += [
        _cpp_constant(f"SCALE_{r.name.upper()}", r.scale_divisor)
        for r in inputs
        if r.scale_divisor > 1
    ]
    out.append("")
    for _cls, table, _doc in _FLAG_CLASSES:
        out += _cpp_bits(table, getattr(m, table))
    out += [_cpp_constant("CRITICAL_VALIDITY", f"{_bit_mask(m.critical_validity_bits):#06x}"), ""]
    for ename in sorted(m.enums):
        members = m.enums[ename]
        out.append(f"enum class {_camel(ename)} : std::uint16_t {{")
        out += [f"    {members[v].upper()} = {v}," for v in sorted(members)]
        out += ["};", ""]
    out += [
        "struct FaultCodeInfo {",
        "    std::uint16_t code;",
        "    FaultSeverity default_severity;",
        "    bool state_dependent;",
        "};",
        "",
        "constexpr FaultCodeInfo FAULT_CODES[] = {",
    ]
    out += [
        f"    {{{fc.code}, FaultSeverity::{fc.default_severity.upper()}, "
        f"{'true' if fc.state_dependent else 'false'}}},"
        for fc in m.fault_codes
    ]
    out += ["};", ""]
    out += _cpp_block(
        "Snapshot",
        "encode_snapshot",
        "INPUT_COUNT",
        [r for r in inputs if not r.reserved],
        m.input_start,
    )
    out += _cpp_block("Metadata", "encode_metadata", "METADATA_COUNT", meta, meta_start)
    out.append("}  // namespace ro::reg")
    return "\n".join(out) + "\n"


def write_cpp(m: RegisterMap, path: Path | None = None) -> None:
    """Write the C++ header with LF newlines, creating its directory.

    :param m: Validated register map.
    :param path: Destination file; defaults to :data:`CPP_PATH`.
    :raises ValueError: If the map cannot be rendered.
    :raises OSError: If the file cannot be written.
    """
    target = path or CPP_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_cpp(m), encoding="utf-8", newline="\n")


def is_cpp_current(m: RegisterMap, path: Path | None = None) -> bool:
    """Report whether the C++ header matches a fresh rendering.

    :param m: Validated register map.
    :param path: File to compare; defaults to :data:`CPP_PATH`.
    :returns: True if the file exists and matches :func:`render_cpp`.
    """
    target = path or CPP_PATH
    return target.exists() and target.read_text(encoding="utf-8") == render_cpp(m)


if __name__ == "__main__":
    _map = schema.load()
    write(_map)
    write_cpp(_map)
