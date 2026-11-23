"""1-Wire device names: the bindings file (``config/onewire_bindings.yaml``).

The bindings file is the single source of truth for which role and display label each
1-Wire ROM carries. Names are display-only and monitoring-only; they never affect
validity, node health or the production permit.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from loguru import logger

from ro_tools.monitor import OneWireBinding
from ro_tools.onewire import parse_rom
from ro_tools.schema import _UniqueKeyLoader

#: Default bindings file location (repository root ``config/``).
DEFAULT_BINDINGS_PATH: Path = (
    Path(__file__).resolve().parents[3] / "config" / "onewire_bindings.yaml"
)
#: The only bindings-file schema version this module understands.
BINDINGS_SCHEMA = 1
#: Longest label, in characters (one LCD row minus the value field).
LABEL_MAX_CHARS = 12

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
                if rom in seen_roms:
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
    :func:`ro_tools.onewire.parse_rom` and unique; ``role`` matching
    ``^[a-z][a-z0-9_]{0,31}$`` and unique; ``label`` 1-12 LCD-safe characters with no
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
