"""Pure in-memory Modbus register bank for the simulated sensor node.

No sockets and no Modbus library: it turns request PDUs into response PDUs.
"""

from __future__ import annotations

import struct
import threading
import time
from collections.abc import Callable

from ro_tools.generated.registers import (
    INPUT_COUNT,
    INPUT_START,
    METADATA_COUNT,
    METADATA_START,
    PROTOCOL_MAJOR,
    PROTOCOL_MINOR,
    SNAPSHOT_LAYOUT,
    STATUS_COUNT,
    STATUS_START,
    TYPE_RANGES,
    ControllerStatus,
    Snapshot,
    StatusBits,
    StatusValidationError,
    decode_status,
    encode_snapshot,
    validate_status,
)

EXC_ILLEGAL_FUNCTION = 0x01
EXC_ILLEGAL_ADDRESS = 0x02
EXC_ILLEGAL_VALUE = 0x03

_TYPES: dict[str, str] = {name: typ for name, typ, _ in SNAPSHOT_LAYOUT}


def _exception(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


class RegisterBank:
    """Double-buffered snapshot plus controller-status mailbox.

    Setters change a pending copy; :meth:`commit` publishes it atomically.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        metadata: tuple[int, int, int] = (1, 0, 1),
    ) -> None:
        """Create a bank that publishes nothing as valid.

        :param clock: Returns the current time in seconds.
        :param metadata: (configuration_schema_version, calibration_revision, device_id).
        """
        self._lock = threading.Lock()
        self._clock = clock
        self._pending: dict[str, int] = {name: 0 for name in _TYPES}
        self._pending["protocol_major"] = PROTOCOL_MAJOR
        self._pending["protocol_minor"] = PROTOCOL_MINOR
        self._pending["sample_interval_ms"] = 1000
        self._published = Snapshot(**self._pending)
        self._frozen = False
        self._boot_time = clock()
        self._metadata = list(metadata)
        self._status_words = [0] * STATUS_COUNT
        self._status: ControllerStatus | None = None
        self._status_rx_ms: int | None = None

    def set_field(self, name: str, raw: int) -> None:
        """Set a pending snapshot field.

        :param name: Snapshot field name.
        :param raw: Raw register-level value.
        :raises KeyError: If ``name`` is not a snapshot field.
        :raises ValueError: If ``raw`` is outside the field's type range.
        """
        typ = _TYPES[name]
        lo, hi = TYPE_RANGES[typ]
        if not lo <= raw <= hi:
            raise ValueError(f"{name}={raw} outside {typ} range {lo}..{hi}")
        with self._lock:
            self._pending[name] = raw

    def set_validity(self, bits: int) -> None:
        """Set the pending validity mask.

        :param bits: Validity bits.
        :raises ValueError: If out of range.
        """
        self.set_field("validity_mask", bits)

    def set_faults(self, bits: int) -> None:
        """Set the pending fault mask.

        :param bits: Fault bits.
        :raises ValueError: If out of range.
        """
        self.set_field("fault_mask", bits)

    def set_status(self, bits: int) -> None:
        """Set the pending module status.

        :param bits: Module status bits.
        :raises ValueError: If out of range.
        """
        self.set_field("module_status", bits)

    def freeze_sequence(self, on: bool) -> None:
        """Stop (or resume) sequence advance on commit.

        :param on: True to freeze the sequence.
        """
        with self._lock:
            self._frozen = on

    def force_critical_age(self, ms: int) -> None:
        """Set the pending critical age, saturating at 65535.

        :param ms: Age in milliseconds.
        :raises ValueError: If ``ms`` is negative.
        """
        if ms < 0:
            raise ValueError(f"critical age must be >= 0, got {ms}")
        self.set_field("critical_age_ms", min(ms, 65535))

    def saturate(self, name: str) -> None:
        """Set a pending field to its type maximum and flag saturation.

        :param name: Snapshot field name.
        :raises KeyError: If ``name`` is not a snapshot field.
        """
        hi = TYPE_RANGES[_TYPES[name]][1]
        with self._lock:
            self._pending[name] = hi
            self._pending["module_status"] |= int(StatusBits.OVERFLOW_OR_SATURATION)

    def commit(self) -> None:
        """Publish the pending snapshot, advancing sequence unless frozen."""
        with self._lock:
            if not self._frozen:
                self._pending["snapshot_sequence"] = (
                    self._pending["snapshot_sequence"] + 1
                ) % 65536
            self._pending["uptime_seconds"] = int(self._clock() - self._boot_time)
            self._published = Snapshot(**self._pending)

    def reboot(self) -> None:
        """Simulate a node reboot: bump boot counter, reset sequence and status mailbox."""
        with self._lock:
            self._pending["boot_counter"] += 1
            self._boot_time = self._clock()
            self._pending["uptime_seconds"] = 0
            self._pending["snapshot_sequence"] = 0
            self._pending["module_status"] |= int(StatusBits.WATCHDOG_RESET_SEEN)
            self._status_words = [0] * STATUS_COUNT
            self._status = None
            self._status_rx_ms = None
            self._published = Snapshot(**self._pending)

    def published(self) -> Snapshot:
        """:returns: The currently published snapshot."""
        with self._lock:
            return self._published

    @property
    def controller_status(self) -> ControllerStatus | None:
        """Last valid controller status, or None."""
        with self._lock:
            return self._status

    @property
    def last_valid_status_received_ms(self) -> int | None:
        """Clock time in ms of the last valid status write, or None."""
        with self._lock:
            return self._status_rx_ms

    def handle_pdu(self, pdu: bytes) -> bytes:
        """Process one request PDU.

        :param pdu: Request PDU (function code onward, no unit id or CRC).
        :returns: Normal or exception response PDU.
        """
        if not pdu:
            return bytes([0x80, EXC_ILLEGAL_FUNCTION])
        with self._lock:
            return self._dispatch(pdu)

    def _dispatch(self, pdu: bytes) -> bytes:
        fc = pdu[0]
        if fc not in (3, 4, 16):
            return _exception(fc, EXC_ILLEGAL_FUNCTION)
        if fc in (3, 4):
            if len(pdu) != 5:
                return _exception(fc, EXC_ILLEGAL_VALUE)
            addr, count = struct.unpack(">HH", pdu[1:])
            if not 1 <= count <= 125:
                return _exception(fc, EXC_ILLEGAL_VALUE)
            end = addr + count
            if fc == 4:
                if addr < INPUT_START or end > INPUT_START + INPUT_COUNT:
                    return _exception(fc, EXC_ILLEGAL_ADDRESS)
                words = encode_snapshot(self._published)[addr - INPUT_START : end - INPUT_START]
            elif METADATA_START <= addr and end <= METADATA_START + METADATA_COUNT:
                words = self._metadata[addr - METADATA_START : end - METADATA_START]
            elif STATUS_START <= addr and end <= STATUS_START + STATUS_COUNT:
                words = self._status_words[addr - STATUS_START : end - STATUS_START]
            else:
                return _exception(fc, EXC_ILLEGAL_ADDRESS)
            return bytes([fc, 2 * len(words)]) + struct.pack(f">{len(words)}H", *words)
        # fc == 16
        if len(pdu) < 6:
            return _exception(fc, EXC_ILLEGAL_VALUE)
        addr, count, byte_count = struct.unpack(">HHB", pdu[1:6])
        if not 1 <= count <= 123 or byte_count != 2 * count or len(pdu) != 6 + byte_count:
            return _exception(fc, EXC_ILLEGAL_VALUE)
        if (addr, count) != (STATUS_START, STATUS_COUNT):
            return _exception(fc, EXC_ILLEGAL_ADDRESS)
        values = list(struct.unpack(f">{count}H", pdu[6:]))
        try:
            validate_status(values)
        except StatusValidationError:
            return _exception(fc, EXC_ILLEGAL_VALUE)
        self._status_words = values
        self._status = decode_status(values)
        self._status_rx_ms = int(self._clock() * 1000)
        return struct.pack(">BHH", 16, addr, count)
