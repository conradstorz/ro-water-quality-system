"""1-Wire device names: bindings file, protocol 1.4 name table and LCD reference rows.

The bindings file (``config/onewire_bindings.yaml``) is the single source of truth for
which role and display label each 1-Wire ROM carries. The controller sends a node the
subset it reports as an 83-word name table (holding 240-322). Names are display-only and
monitoring-only; they never affect validity, node health or the production permit.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from loguru import logger

from ro_tools.generated.registers import (
    NAMES_COUNT,
    NAMES_ENTRY_BASE,
    NAMES_ENTRY_MAX,
    NAMES_ENTRY_STRIDE,
    NAMES_LABEL_MAX_CHARS,
    NAMES_LABEL_WORDS,
    NAMES_ROM_WORDS,
    NAMES_SCHEMA_MAJOR,
    NAMES_START,
)
from ro_tools.monitor import OneWireBinding, _slot_unusable_cause
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    SlotReading,
    SlotStatus,
    parse_rom,
    rom_crc_ok,
    rom_family,
)
from ro_tools.schema import _UniqueKeyLoader
from ro_tools.sim.frames import crc16

#: Default bindings file location (repository root ``config/``).
DEFAULT_BINDINGS_PATH: Path = (
    Path(__file__).resolve().parents[3] / "config" / "onewire_bindings.yaml"
)
#: The only bindings-file schema version this module understands.
BINDINGS_SCHEMA = 1
#: Longest label, in characters: 20 LCD columns minus a space, the 7-character value
#: field and the column-20 indicator (``label_max_chars`` in the register map).
LABEL_MAX_CHARS = NAMES_LABEL_MAX_CHARS

_ROLE = re.compile(r"[a-z][a-z0-9_]{0,31}")
_DEVICE_KEYS = frozenset({"rom", "role", "label"})
_TOP_KEYS = frozenset({"schema", "devices"})


class BindingsError(ValueError):
    """Raised when a bindings file is invalid.

    :ivar violations: Every violation found, one human-readable string each.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations: list[str] = list(violations)
        super().__init__(
            f"{len(self.violations)} 1-Wire bindings violation(s):\n  - "
            + "\n  - ".join(self.violations)
        )


def is_lcd_safe(char: str) -> bool:
    """Check one character against the LCD-safe set.

    The set is printable ASCII 0x20-0x7D except ``\\`` (0x5C) and ``~`` (0x7E), which
    assumes the HD44780 A00 character ROM.

    :param char: A single character.
    :returns: True if the character renders as itself on the LCD.
    """
    code = ord(char)
    return 0x20 <= code <= 0x7D and code != 0x5C


def _label_problems(label: str) -> list[str]:
    """:returns: Why ``label`` is not a valid bindings-file label (empty if valid)."""
    problems: list[str] = []
    if not 1 <= len(label) <= LABEL_MAX_CHARS:
        problems.append(f"must be 1-{LABEL_MAX_CHARS} characters, got {len(label)}")
    bad = sorted({c for c in label if not is_lcd_safe(c)})
    if bad:
        problems.append(f"characters outside the LCD-safe set: {bad!r}")
    if label != label.strip(" "):
        problems.append("leading or trailing space")
    return problems


def _device_violations(
    where: str,
    device: object,
    seen_roms: dict[int, str],
    seen_roles: dict[str, str],
    seen_labels: dict[str, str],
) -> list[str]:
    """Check one ``devices`` entry, recording its ROM, role and label as seen.

    :param where: Location prefix for messages, e.g. ``devices[0]``.
    :param device: The entry as loaded from YAML.
    :param seen_roms: Parsed ROMs already seen, mapped to their location.
    :param seen_roles: Roles already seen, mapped to their location.
    :param seen_labels: Labels already seen, mapped to their location.
    :returns: Every violation in this entry.
    """
    if not isinstance(device, dict):
        return [f"{where}: must be a mapping with keys rom, role, label"]
    bad: list[str] = []
    missing = sorted(_DEVICE_KEYS - device.keys())
    unknown = sorted(str(k) for k in device.keys() - _DEVICE_KEYS)
    if missing:
        bad.append(f"{where}: missing key(s) {', '.join(missing)}")
    if unknown:
        bad.append(f"{where}: unknown key(s) {', '.join(unknown)}")

    if "rom" in device:
        rom_text = device["rom"]
        if not isinstance(rom_text, str):
            bad.append(f"{where}.rom: must be a string of 16 hex digits (quote it)")
        else:
            try:
                rom = parse_rom(rom_text)
            except ValueError as exc:
                bad.append(f"{where}.rom: {exc}")
            else:
                if rom == 0:
                    bad.append(f"{where}.rom: all-zero ROM is not a device (its CRC-8 is 0)")
                elif rom in seen_roms:
                    bad.append(f"{where}.rom: duplicate of {seen_roms[rom]}.rom")
                else:
                    seen_roms[rom] = where

    if "role" in device:
        role = device["role"]
        if not isinstance(role, str) or not _ROLE.fullmatch(role):
            bad.append(f"{where}.role: {role!r} does not match ^[a-z][a-z0-9_]{{0,31}}$")
        elif role in seen_roles:
            bad.append(f"{where}.role: duplicate of {seen_roles[role]}.role")
        else:
            seen_roles[role] = where

    if "label" in device:
        label = device["label"]
        if not isinstance(label, str):
            bad.append(f"{where}.label: must be a string (quote it)")
        else:
            problems = _label_problems(label)
            bad.extend(f"{where}.label {label!r}: {p}" for p in problems)
            if not problems:
                if label in seen_labels:
                    bad.append(f"{where}.label: duplicate of {seen_labels[label]}.label")
                else:
                    seen_labels[label] = where
    return bad


def validate_bindings_data(data: object) -> list[str]:
    """Check loaded bindings-file data against every rule.

    Rules: a top-level mapping with exactly ``schema: 1`` and a ``devices`` list; each
    device a mapping with exactly ``rom``, ``role`` and ``label``; ``rom`` valid per
    :func:`ro_tools.onewire.parse_rom`, not all zero, and unique; ``role`` matching
    ``^[a-z][a-z0-9_]{0,31}$`` and unique; ``label`` 1-11 LCD-safe characters with no
    leading/trailing space, unique. An empty ``devices`` list is valid.

    :param data: Result of safe-loading the YAML file.
    :returns: Every violation found; empty if the data is valid.
    """
    if not isinstance(data, dict):
        return ["top level must be a mapping with keys schema, devices"]
    bad: list[str] = []
    unknown = sorted(str(k) for k in data.keys() - _TOP_KEYS)
    if unknown:
        bad.append(f"unknown top-level key(s) {', '.join(unknown)}")
    schema = data.get("schema")
    if type(schema) is not int or schema != BINDINGS_SCHEMA:
        bad.append(f"schema: must be {BINDINGS_SCHEMA}, got {schema!r}")
    if "devices" not in data:
        bad.append("devices: missing (use 'devices: []' for none)")
        return bad
    devices = data["devices"]
    if not isinstance(devices, list):
        bad.append("devices: must be a list")
        return bad
    seen_roms: dict[int, str] = {}
    seen_roles: dict[str, str] = {}
    seen_labels: dict[str, str] = {}
    for i, device in enumerate(devices):
        bad.extend(_device_violations(f"devices[{i}]", device, seen_roms, seen_roles, seen_labels))
    return bad


def load_bindings(path: Path = DEFAULT_BINDINGS_PATH) -> tuple[OneWireBinding, ...]:
    """Read and validate a bindings file.

    :param path: Location of the YAML file.
    :returns: One :class:`~ro_tools.monitor.OneWireBinding` per device, in file order.
    :raises BindingsError: (a :class:`ValueError`) listing every violation, including
        repeated mapping keys and YAML syntax errors.
    :raises OSError: If the file cannot be read.
    """
    path = Path(path)
    loader = _UniqueKeyLoader(path.read_text(encoding="utf-8"))
    try:
        data = loader.get_single_data()
    except yaml.YAMLError as exc:
        raise BindingsError([f"{path}: invalid YAML: {exc}"]) from exc
    finally:
        loader.dispose()
    violations = list(loader.duplicates) + validate_bindings_data(data)
    if violations:
        raise BindingsError(violations)
    bindings = tuple(
        OneWireBinding(role=d["role"], rom=parse_rom(d["rom"]), label=d["label"])
        for d in data["devices"]
    )
    logger.debug("loaded {} 1-Wire binding(s) from {}", len(bindings), path)
    return bindings


# --------------------------------------------------------------------------------------
# Protocol 1.4 name table (holding registers 240-322)
# --------------------------------------------------------------------------------------

_U16_MAX = 0xFFFF
_LABEL_BYTES = 2 * NAMES_LABEL_WORDS
#: Offset of entry 0 within the 83-word table (table word 0 is holding 240).
_ENTRY0 = NAMES_ENTRY_BASE - NAMES_START


@dataclass(frozen=True)
class NameEntry:
    """One name-table entry: a ROM and the label the node displays for it.

    :ivar rom: 64-bit ROM ID (family in the low byte, CRC-8 in the high byte).
    :ivar label: Display label, 1-11 LCD-safe characters.
    """

    rom: int
    label: str


class NameTableError(ValueError):
    """Raised when a name table is invalid.

    :ivar violations: Every violation found, one human-readable string each.
    """

    def __init__(self, violations: list[str]) -> None:
        self.violations: list[str] = list(violations)
        super().__init__(
            f"{len(self.violations)} name table violation(s):\n  - "
            + "\n  - ".join(self.violations)
        )


def _rom_to_words(rom: int) -> list[int]:
    """Split a ROM into the 4-word input-slot encoding (``rom0`` = bits 63..48).

    :param rom: 64-bit ROM integer.
    :returns: ``[rom0, rom1, rom2, rom3]``.
    """
    return [(rom >> (48 - 16 * w)) & _U16_MAX for w in range(NAMES_ROM_WORDS)]


def _words_to_rom(words: Sequence[int]) -> int:
    """:returns: The 64-bit ROM folded from 4 ROM words, ``rom0`` first."""
    rom = 0
    for word in words:
        rom = (rom << 16) | word
    return rom


def _entry_base(n: int) -> int:
    """:returns: Offset of entry ``n`` within the 83-word table."""
    return _ENTRY0 + NAMES_ENTRY_STRIDE * n


def _label_bytes(words: Sequence[int]) -> bytes:
    """:returns: The 12 label bytes of 6 label words, high byte first."""
    return bytes(b for w in words for b in ((w >> 8) & 0xFF, w & 0xFF))


def _node_label_problems(label: str) -> list[str]:
    """Node-side label rules (no leading/trailing-space rule, unlike the bindings file).

    :param label: Candidate label.
    :returns: Why ``label`` cannot go in the name table (empty if it can).
    """
    problems: list[str] = []
    if not 1 <= len(label) <= LABEL_MAX_CHARS:
        problems.append(f"must be 1-{LABEL_MAX_CHARS} characters, got {len(label)}")
    bad = sorted({c for c in label if not is_lcd_safe(c)})
    if bad:
        problems.append(f"characters outside the LCD-safe set: {bad!r}")
    return problems


def encode_name_table(entries: Sequence[NameEntry], revision: int) -> list[int]:
    """Encode the 83-word name table for an FC16 write of holding 240-322.

    Layout: ``names_schema_major`` (1), ``names_revision``, ``names_entry_count``, then
    8 entries of ``rom0..rom3`` (same encoding as the input slots) and 6 label words
    (ASCII, 2 characters per word, high byte first, NUL-padded). Unused entries are zero.
    Entries are written in the order given.

    :param entries: At most 8 entries with distinct, CRC-valid, non-zero ROMs.
    :param revision: Opaque u16 revision (the controller uses :func:`bindings_revision`).
    :returns: 83 register words.
    :raises ValueError: On more than 8 entries, a revision outside u16, a ROM outside
        64 bits, all zero or with a bad CRC-8, a duplicate ROM, or an invalid label
        (empty, over 11 characters or outside the LCD-safe set).
    """
    if len(entries) > NAMES_ENTRY_MAX:
        raise ValueError(f"{len(entries)} entries; at most {NAMES_ENTRY_MAX} allowed")
    if not 0 <= revision <= _U16_MAX:
        raise ValueError(f"revision {revision} outside 0..65535")
    words = [0] * NAMES_COUNT
    words[0] = NAMES_SCHEMA_MAJOR
    words[1] = revision
    words[2] = len(entries)
    seen: set[int] = set()
    for n, entry in enumerate(entries):
        if not 0 <= entry.rom < 1 << 64:
            raise ValueError(f"entry {n}: rom {entry.rom} outside 64 bits")
        if entry.rom == 0:
            raise ValueError(f"entry {n}: all-zero ROM is not a device")
        if not rom_crc_ok(entry.rom):
            raise ValueError(f"entry {n}: ROM {entry.rom:016X} fails its CRC-8")
        if entry.rom in seen:
            raise ValueError(f"entry {n}: duplicate ROM {entry.rom:016X}")
        seen.add(entry.rom)
        problems = _node_label_problems(entry.label)
        if problems:
            raise ValueError(f"entry {n}: label {entry.label!r}: {'; '.join(problems)}")
        raw = entry.label.encode("ascii").ljust(_LABEL_BYTES, b"\0")
        base = _entry_base(n)
        words[base : base + NAMES_ROM_WORDS] = _rom_to_words(entry.rom)
        for w in range(NAMES_LABEL_WORDS):
            words[base + NAMES_ROM_WORDS + w] = (raw[2 * w] << 8) | raw[2 * w + 1]
    return words


def _entry_label_violations(n: int, raw: bytes) -> list[str]:
    """Check the 12 label bytes of used entry ``n`` (node-side rules).

    :param n: Entry index, for messages.
    :param raw: The label bytes, high byte of the first word first.
    :returns: Every label violation of this entry.
    """
    bad: list[str] = []
    if raw[0] == 0:
        bad.append(f"entry {n}: label is empty")
    if any(raw[LABEL_MAX_CHARS:]):
        bad.append(
            f"entry {n}: label longer than {LABEL_MAX_CHARS} characters "
            f"(byte(s) after the {LABEL_MAX_CHARS}th must be NUL)"
        )
    unsafe = sorted({b for b in raw if b and not is_lcd_safe(chr(b))})
    if unsafe:
        codes = ", ".join(f"0x{b:02X}" for b in unsafe)
        bad.append(f"entry {n}: label byte(s) outside the LCD-safe set: {codes}")
    first_nul = raw.find(0)
    if first_nul != -1 and any(raw[first_nul:]):
        bad.append(f"entry {n}: label has an embedded NUL (NUL followed by non-NUL)")
    return bad


def validate_name_table(words: Sequence[int]) -> list[str]:
    """Check an 83-word name table against the node-side rules.

    The node rejects the whole write (ILLEGAL_DATA_VALUE, previous table kept) when:
    the length is not 83; ``names_schema_major != 1``; ``names_entry_count > 8``; a used
    entry (n < count) has an all-zero ROM (whose CRC-8 is 0, so it would pass the CRC
    check), a bad ROM CRC-8, an empty label, a label longer than 11 characters (the 12th
    byte, the low byte of ``label5``, must be NUL), a label byte outside the LCD-safe
    set, or a NUL followed by a non-NUL; a ROM appears twice among used entries;
    or any word of an unused entry is non-zero. Leading/trailing label spaces are allowed
    here (only the bindings file forbids them). A word outside 0..65535 is also reported
    (it cannot occur on the wire).

    :param words: Register words for holding 240-322.
    :returns: Every violation; empty means accept.
    """
    if len(words) != NAMES_COUNT:
        return [f"table must be {NAMES_COUNT} words, got {len(words)}"]
    out_of_range = [i for i, w in enumerate(words) if not 0 <= w <= _U16_MAX]
    if out_of_range:
        return [f"word(s) outside u16 at offset(s) {out_of_range}"]
    bad: list[str] = []
    if words[0] != NAMES_SCHEMA_MAJOR:
        bad.append(f"names_schema_major must be {NAMES_SCHEMA_MAJOR}, got {words[0]}")
    count = words[2]
    if count > NAMES_ENTRY_MAX:
        bad.append(f"names_entry_count {count} exceeds {NAMES_ENTRY_MAX}")
    used = min(count, NAMES_ENTRY_MAX)
    seen: dict[int, int] = {}
    for n in range(NAMES_ENTRY_MAX):
        base = _entry_base(n)
        entry_words = words[base : base + NAMES_ENTRY_STRIDE]
        if n >= used:
            if any(entry_words):
                bad.append(f"entry {n}: unused entry is not all zero")
            continue
        rom = _words_to_rom(entry_words[:NAMES_ROM_WORDS])
        if rom == 0:
            bad.append(f"entry {n}: all-zero ROM is not a device")
        elif not rom_crc_ok(rom):
            bad.append(f"entry {n}: ROM {rom:016X} fails its CRC-8")
        if rom in seen:
            bad.append(f"entry {n}: duplicate ROM {rom:016X} (also entry {seen[rom]})")
        else:
            seen[rom] = n
        bad.extend(_entry_label_violations(n, _label_bytes(entry_words[NAMES_ROM_WORDS:])))
    return bad


def decode_name_table(words: Sequence[int]) -> tuple[int, tuple[NameEntry, ...]]:
    """Decode an 83-word name table (e.g. an FC03 read-back of holding 240-322).

    :param words: Register words for holding 240-322.
    :returns: ``(revision, entries)`` with entries in table order.
    :raises NameTableError: (a :class:`ValueError`) listing every violation of
        :func:`validate_name_table`.
    """
    violations = validate_name_table(words)
    if violations:
        raise NameTableError(violations)
    entries: list[NameEntry] = []
    for n in range(words[2]):
        base = _entry_base(n)
        rom = _words_to_rom(words[base : base + NAMES_ROM_WORDS])
        raw = _label_bytes(words[base + NAMES_ROM_WORDS : base + NAMES_ENTRY_STRIDE])
        entries.append(NameEntry(rom, raw.rstrip(b"\0").decode("ascii")))
    return words[1], tuple(entries)


def select_for_node(
    bindings: Sequence[OneWireBinding], slots: Sequence[SlotReading]
) -> tuple[NameEntry, ...]:
    """Choose the entries to send one node: bindings for the ROMs it reports present.

    :param bindings: All bindings (from :func:`load_bindings`).
    :param slots: The node's decoded slots (:func:`ro_tools.onewire.decode_slots`).
    :returns: Entries for bindings whose ROM is in a slot with PRESENT set, sorted by
        ROM ascending, truncated to 8 (a warning is logged if truncated).
    """
    present = {s.rom for s in slots if s.status & SlotStatus.PRESENT}
    chosen = sorted(
        (NameEntry(b.rom, b.label) for b in bindings if b.rom in present),
        key=lambda e: e.rom,
    )
    if len(chosen) > NAMES_ENTRY_MAX:
        logger.warning(
            "{} bound 1-Wire devices present; sending only the first {} by ROM",
            len(chosen),
            NAMES_ENTRY_MAX,
        )
        chosen = chosen[:NAMES_ENTRY_MAX]
    return tuple(chosen)


def bindings_revision(path: Path = DEFAULT_BINDINGS_PATH) -> int:
    """Compute the name-table revision of a bindings file.

    :param path: Location of the bindings file.
    :returns: CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF) of the file bytes.
    :raises OSError: If the file cannot be read.
    """
    return crc16(Path(path).read_bytes())


# --------------------------------------------------------------------------------------
# Reference LCD rows (spec section 3)
# --------------------------------------------------------------------------------------

#: LCD rows per page.
LCD_ROWS = 4
#: LCD columns per row.
LCD_COLS = 20
#: Width of the right-aligned value field.
VALUE_WIDTH = 7
#: Default content of column 20, which every LCD page reserves for a fault/status
#: indicator (owner decision 2026-11-23; the glyph itself is not yet designed).
INDICATOR_BLANK = " "
if LABEL_MAX_CHARS + 1 + VALUE_WIDTH + 1 != LCD_COLS:  # label, space, value, indicator
    raise RuntimeError(f"label_max_chars {LABEL_MAX_CHARS} does not fit the 20-column row")
_VALUE_INVALID = "---"
_VALUE_ERROR = "ERR"


def _fit(value: str) -> str:
    """:returns: ``value`` right-aligned to 7 characters, or ``ERR`` if it is longer."""
    return (value if len(value) <= VALUE_WIDTH else _VALUE_ERROR).rjust(VALUE_WIDTH)


def format_temperature(centi_c: int) -> str:
    """Format degC x100 as one decimal plus ``C``, e.g. ``2150`` -> ``21.5C``.

    Rounds half away from zero in integer arithmetic (``2155`` -> ``21.6C``,
    ``-2155`` -> ``-21.6C``). A value that rounds to zero prints ``0.0C``, never
    ``-0.0C``.

    :param centi_c: Temperature in hundredths of a degree Celsius.
    :returns: The unpadded value text.
    """
    tenths, rem = divmod(abs(centi_c), 10)
    if rem >= 5:
        tenths += 1
    sign = "-" if centi_c < 0 and tenths else ""
    return f"{sign}{tenths // 10}.{tenths % 10}C"


def format_millivolts(mv: int) -> str:
    """:returns: ``mv`` as an integer plus ``mV``, e.g. ``3300mV``."""
    return f"{mv}mV"


def unnamed_label(rom: int) -> str:
    """Label shown for a device with no name entry.

    ``?`` + family (2 hex digits) + ``-`` + the low 16 bits of the 48-bit serial
    (4 hex digits), e.g. ``?28-1BFF`` for ROM text ``28FF1B2C3D5F4EDE``.

    :param rom: 64-bit ROM integer.
    :returns: The label text (8 characters).
    """
    return f"?{rom_family(rom):02X}-{(rom >> 8) & 0xFFFF:04X}"


def render_onewire_rows(
    slots: Sequence[SlotReading],
    entries: Sequence[NameEntry],
    indicator: str = INDICATOR_BLANK,
) -> list[str]:
    """Render reference 20-column LCD rows for the 1-Wire pages (spec section 3).

    For each slot with PRESENT set, in slot order: label (the entry's label, else
    :func:`unnamed_label`) left-justified to 11, a space, a 7-character right-aligned
    value, and ``indicator`` in column 20. DS18B20: one row with the temperature.
    DS2438: the label row with the temperature, then 12 spaces, the mV value and the
    indicator (two rows even when not usable). Other families: one label row with
    ``---``. A slot that is not usable (same rule as
    :func:`ro_tools.monitor.evaluate_onewire`, so unknown status bits count) shows
    ``---``; a value longer than 7 characters shows ``ERR``. Paging is left to the
    caller (see :func:`paginate`).

    :param slots: Decoded slots (:func:`ro_tools.onewire.decode_slots`).
    :param entries: Name entries, e.g. from :func:`decode_name_table`.
    :param indicator: One LCD-safe character for column 20 (default a space). Column 20
        is reserved on every page for a fault/status indicator.
    :returns: Every row, each exactly 20 characters.
    :raises ValueError: If ``indicator`` is not one LCD-safe character, or an entry's
        label breaks the node-side label rules.
    """
    if not isinstance(indicator, str) or len(indicator) != 1 or not is_lcd_safe(indicator):
        raise ValueError(f"indicator {indicator!r} must be one LCD-safe character")
    labels: dict[int, str] = {}
    for entry in entries:
        problems = _node_label_problems(entry.label)
        if problems:
            raise ValueError(f"label {entry.label!r}: {'; '.join(problems)}")
        labels[entry.rom] = entry.label
    rows: list[str] = []
    for slot in slots:
        if not slot.status & SlotStatus.PRESENT:
            continue
        label = labels.get(slot.rom, unnamed_label(slot.rom)).ljust(LABEL_MAX_CHARS)
        usable = _slot_unusable_cause(slot) is None
        family = rom_family(slot.rom)
        if family in (FAMILY_DS18B20, FAMILY_DS2438) and usable:
            primary = _fit(format_temperature(slot.primary))
        else:
            primary = _fit(_VALUE_INVALID)
        rows.append(f"{label} {primary}{indicator}")
        if family == FAMILY_DS2438:
            secondary = _fit(format_millivolts(slot.secondary) if usable else _VALUE_INVALID)
            rows.append(" " * (LABEL_MAX_CHARS + 1) + secondary + indicator)
    return rows


def paginate(rows: Sequence[str], per_page: int = LCD_ROWS) -> list[list[str]]:
    """Split rows into pages of ``per_page`` rows (the last page may be shorter).

    :param rows: Rows from :func:`render_onewire_rows`.
    :param per_page: Rows per page.
    :returns: The pages; empty if there are no rows.
    :raises ValueError: If ``per_page`` is not positive.
    """
    if per_page < 1:
        raise ValueError(f"per_page {per_page} must be positive")
    return [list(rows[i : i + per_page]) for i in range(0, len(rows), per_page)]


# --------------------------------------------------------------------------------------
# Controller push policy (spec section 5; pure, no I/O)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class NodeObservation:
    """What the controller knows about one node when deciding whether to push names.

    :ivar unit_id: Modbus unit id of the node.
    :ivar boot_counter: The node's ``boot_counter`` from its latest snapshot.
    :ivar scan_generation: The node's ``onewire_scan_generation`` from its latest snapshot.
    :ivar revision: Revision of the bindings file (:func:`bindings_revision`).
    """

    unit_id: int
    boot_counter: int
    scan_generation: int
    revision: int


class NamePushPolicy:
    """Decide when the controller (re)pushes a node's name table.

    Push on first contact with a node, or when its ``boot_counter``, its
    ``onewire_scan_generation`` or the bindings revision differs from the last
    successful push. A node marked unsupported (it answered ILLEGAL_DATA_ADDRESS, a
    protocol 1.3 node) is not pushed again until its ``boot_counter`` changes. A push
    that fails for any other reason is simply not recorded, so it is retried on the
    next observation. The policy never affects node health or the production permit.
    """

    def __init__(self) -> None:
        """Start with no node contacted."""
        self._pushed: dict[int, NodeObservation] = {}
        self._unsupported_boot: dict[int, int] = {}

    def should_push(self, observed: NodeObservation) -> bool:
        """:returns: True if the node's name table should be written now."""
        unsupported_boot = self._unsupported_boot.get(observed.unit_id)
        if unsupported_boot is not None:
            return observed.boot_counter != unsupported_boot
        return self._pushed.get(observed.unit_id) != observed

    def record_pushed(self, observed: NodeObservation) -> None:
        """Record a push that was written and verified by read-back.

        :param observed: The observation the push was made for.
        """
        self._pushed[observed.unit_id] = observed
        self._unsupported_boot.pop(observed.unit_id, None)

    def record_unsupported(self, observed: NodeObservation) -> None:
        """Mark the node "names unsupported" until its ``boot_counter`` changes.

        :param observed: The observation for which the node answered ILLEGAL_DATA_ADDRESS.
        """
        self._unsupported_boot[observed.unit_id] = observed.boot_counter
        self._pushed.pop(observed.unit_id, None)

    def supported(self, unit_id: int) -> bool:
        """:returns: False while the node is marked "names unsupported", else True."""
        return unit_id not in self._unsupported_boot
