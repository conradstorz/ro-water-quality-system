"""1-Wire ROM/slot model and simulated devices for register block 140-199.

ROM convention (binding): the 64-bit ROM integer carries the family code in the LOW
byte, the 48-bit serial in bytes 1-6 and the CRC-8 in the HIGH byte (bits 63..56).
``rom0`` is bits 63..48 and ``rom3`` is bits 15..0. The CRC is computed over the low
7 bytes taken low byte first.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import IntFlag

from ro_tools.generated.registers import Snapshot

SLOT_COUNT = 8
FAMILY_DS18B20 = 0x28
FAMILY_DS2438 = 0x26
_SUPPORTED_FAMILIES = frozenset({FAMILY_DS18B20, FAMILY_DS2438})
_U16_MAX = 65535


class SlotStatus(IntFlag):
    """Per-slot status bits."""

    PRESENT = 1
    VALID = 2
    STALE = 4
    CRC_ERROR = 8
    UNSUPPORTED_FAMILY = 16
    MISSING = 32


class BusStatus(IntFlag):
    """Bus-level status bits."""

    BUS_SHORT = 1
    NO_PRESENCE = 2
    CRC_ERRORS = 4
    OVERFLOW = 8


NO_BUS_STATUS = BusStatus(0)


def dallas_crc8(data: bytes) -> int:
    """Compute the Maxim/Dallas CRC-8 (reflected polynomial 0x8C).

    :param data: Input bytes.
    :returns: CRC-8 value.
    """
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc


def make_rom(family: int, serial: int) -> int:
    """Build a 64-bit ROM ID.

    :param family: Family code (low byte).
    :param serial: 48-bit serial number.
    :returns: ROM integer with the CRC-8 in the high byte.
    :raises ValueError: If ``family`` or ``serial`` is out of range.
    """
    if not 0 <= family <= 0xFF:
        raise ValueError(f"family {family} outside 0..255")
    if not 0 <= serial < 1 << 48:
        raise ValueError(f"serial {serial} outside 48 bits")
    low = family | (serial << 8)
    return low | (dallas_crc8(low.to_bytes(7, "little")) << 56)


def rom_family(rom: int) -> int:
    """:returns: Family code of ``rom`` (its low byte)."""
    return rom & 0xFF


def rom_crc_ok(rom: int) -> bool:
    """Check the CRC-8 in the high byte against the low 7 bytes.

    :param rom: 64-bit ROM integer.
    :returns: True if the CRC matches.
    """
    return (rom >> 56) == dallas_crc8((rom & ((1 << 56) - 1)).to_bytes(7, "little"))


@dataclass(frozen=True)
class OneWireDevice:
    """A simulated 1-Wire device."""

    rom: int
    primary: int = 0
    secondary: int = 0
    present: bool = True
    valid: bool = True
    stale: bool = False
    crc_error: bool = False
    missing: bool = False

    def __post_init__(self) -> None:
        """Validate the device description.

        :raises ValueError: If ``rom`` is not a 64-bit value, or ``present`` and
            ``missing`` are not exactly one of each (a device is present or missing).
        """
        if not 0 <= self.rom < 1 << 64:
            raise ValueError(f"rom {self.rom} outside 64 bits")
        if self.present == self.missing:
            raise ValueError("a device must be exactly one of present or missing")


@dataclass(frozen=True)
class SlotReading:
    """A decoded, non-empty slot."""

    rom: int
    primary: int
    secondary: int
    status: SlotStatus
    slot: int = 0

    @property
    def usable(self) -> bool:
        """True only when PRESENT and VALID are set and no fault bit is set."""
        bad = (
            SlotStatus.STALE
            | SlotStatus.CRC_ERROR
            | SlotStatus.MISSING
            | SlotStatus.UNSUPPORTED_FAMILY
        )
        return (
            bool(self.status & SlotStatus.PRESENT)
            and bool(self.status & SlotStatus.VALID)
            and not self.status & bad
        )


def _slot_words(device: OneWireDevice) -> tuple[int, int, int]:
    """Compute ``(primary, secondary, status)`` for one device.

    :param device: Simulated device.
    :returns: Primary value, secondary value and status bits.
    """
    status = SlotStatus(0)
    primary, secondary = device.primary, device.secondary
    if device.present:
        status |= SlotStatus.PRESENT
    if device.missing:
        status |= SlotStatus.MISSING
    if device.stale:
        status |= SlotStatus.STALE
    if device.valid:
        status |= SlotStatus.VALID
    if device.crc_error:
        status |= SlotStatus.CRC_ERROR
    if rom_family(device.rom) not in _SUPPORTED_FAMILIES:
        status |= SlotStatus.UNSUPPORTED_FAMILY
    if status & (SlotStatus.CRC_ERROR | SlotStatus.UNSUPPORTED_FAMILY | SlotStatus.MISSING):
        status &= ~SlotStatus.VALID
    if not status & SlotStatus.VALID:
        primary = secondary = 0
    return primary, secondary, int(status)


def encode_onewire(
    devices: Sequence[OneWireDevice],
    bus_status: BusStatus = NO_BUS_STATUS,
    age_ms: int = 0,
    generation: int = 0,
) -> dict[str, int]:
    """Encode devices into snapshot fields for registers 140-199.

    :param devices: Devices on the bus; sorted by ROM, truncated to 8.
    :param bus_status: Bus status bits (OVERFLOW is added if truncated).
    :param age_ms: Age of the scan in ms, saturating at 65535.
    :param generation: Scan generation counter.
    :returns: Mapping of snapshot field name to raw register value.
    :raises ValueError: If two devices share a ROM or ``age_ms`` is negative.
    """
    if age_ms < 0:
        raise ValueError(f"age_ms {age_ms} is negative")
    roms = [d.rom for d in devices]
    if len(set(roms)) != len(roms):
        raise ValueError("duplicate ROM on bus")
    ordered = sorted(devices, key=lambda d: d.rom)
    status = BusStatus(bus_status)
    if len(ordered) > SLOT_COUNT:
        status |= BusStatus.OVERFLOW
        ordered = ordered[:SLOT_COUNT]
    fields: dict[str, int] = {
        "onewire_device_count": 0,
        "onewire_bus_status": int(status),
        "onewire_scan_generation": generation,
        "onewire_age_ms": min(age_ms, _U16_MAX),
    }
    count = 0
    for i in range(SLOT_COUNT):
        prefix = f"onewire_s{i}_"
        dev = ordered[i] if i < len(ordered) else None
        rom = dev.rom if dev else 0
        primary, secondary, st = _slot_words(dev) if dev else (0, 0, 0)
        for w in range(4):
            fields[f"{prefix}rom{w}"] = (rom >> (48 - 16 * w)) & 0xFFFF
        fields[f"{prefix}primary"] = primary
        fields[f"{prefix}secondary"] = secondary
        fields[f"{prefix}status"] = st
        if st & SlotStatus.PRESENT:
            count += 1
    fields["onewire_device_count"] = count
    return fields


def decode_slots(snapshot: Snapshot) -> tuple[SlotReading, ...]:
    """Decode the non-empty slots of a snapshot, in slot order.

    :param snapshot: Snapshot carrying the 1-Wire block.
    :returns: One :class:`SlotReading` per slot with any non-zero word.
    """
    out: list[SlotReading] = []
    for i in range(SLOT_COUNT):
        prefix = f"onewire_s{i}_"
        words = [getattr(snapshot, f"{prefix}rom{w}") for w in range(4)]
        primary = getattr(snapshot, f"{prefix}primary")
        secondary = getattr(snapshot, f"{prefix}secondary")
        status = getattr(snapshot, f"{prefix}status")
        if not (any(words) or primary or secondary or status):
            continue
        rom = 0
        for word in words:
            rom = (rom << 16) | word
        out.append(SlotReading(rom, primary, secondary, SlotStatus(status), i))
    return tuple(out)
