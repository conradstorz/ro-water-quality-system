"""Pure in-memory Modbus register bank for the simulated sensor node.

No sockets and no Modbus library: it turns request PDUs into response PDUs.
"""

from __future__ import annotations

import functools
import operator
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
    NodeType,
    Snapshot,
    StatusBits,
    StatusValidationError,
    ValidityBits,
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


_U32_MAX: int = TYPE_RANGES["u32"][1]

ALL_SENSORS: int = functools.reduce(operator.or_, (int(bit) for bit in ValidityBits), 0)


def _check_identity(node_type: int, installed_mask: int) -> None:
    """Reject an impossible node identity.

    :param node_type: Candidate ``node_type`` register value.
    :param installed_mask: Candidate ``installed_mask`` register value.
    :raises ValueError: If ``node_type`` is not a defined :class:`NodeType` value or
        ``installed_mask`` has a bit that is not a defined validity bit.
    """
    if node_type not in {int(member) for member in NodeType}:
        raise ValueError(f"node_type {node_type} is not a defined NodeType")
    if installed_mask < 0 or installed_mask & ~ALL_SENSORS:
        raise ValueError(f"installed_mask {installed_mask:#06x} has undefined sensor bits")


class RegisterBank:
    """Double-buffered snapshot plus controller-status mailbox.

    Setters change a pending copy; :meth:`commit` publishes it atomically.
    All public methods are thread-safe.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        metadata: tuple[int, int, int] = (1, 0, 1),
        node_type: int = int(NodeType.RO_SKID),
        installed_mask: int = ALL_SENSORS,
    ) -> None:
        """Create a bank that publishes nothing as valid.

        :param clock: Returns the current time in seconds.
        :param metadata: (configuration_schema_version, calibration_revision, device_id).
        :param node_type: A :class:`NodeType` value; defaults to the full RO skid.
        :param installed_mask: Validity bits that are physically fitted; defaults to every
            sensor.
        :raises ValueError: If ``node_type`` or ``installed_mask`` is impossible.
        """
        self._lock = threading.Lock()
        self._clock = clock
        self._pending: dict[str, int] = {name: 0 for name in _TYPES}
        self._pending["protocol_major"] = PROTOCOL_MAJOR
        self._pending["protocol_minor"] = PROTOCOL_MINOR
        self._pending["sample_interval_ms"] = 1000
        _check_identity(node_type, installed_mask)
        self._pending["node_type"] = node_type
        self._pending["installed_mask"] = installed_mask
        self._published = Snapshot(**self._pending)
        self._frozen = False
        self._boot_time = clock()
        self._metadata = list(metadata)
        self._status_words = [0] * STATUS_COUNT
        self._status: ControllerStatus | None = None
        self._status_rx_ms: int | None = None
        self._status_progress_ms: int | None = None
        self._last_rejection: str | None = None

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

    def configure_node(self, node_type: int, installed_mask: int) -> None:
        """Change the pending node identity.

        :param node_type: A :class:`NodeType` value.
        :param installed_mask: Bits of the validity mask that are physically fitted.
        :raises ValueError: If either value is impossible (see :func:`_check_identity`).
        """
        _check_identity(node_type, installed_mask)
        with self._lock:
            self._pending["node_type"] = node_type
            self._pending["installed_mask"] = installed_mask

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

    def _require_validity_installed(self) -> None:
        """Check that every pending validity bit is a fitted sensor (lock held).

        :raises ValueError: If a validity bit is set for a sensor that is not installed.
        """
        unfitted = self._pending["validity_mask"] & ~self._pending["installed_mask"]
        if unfitted:
            raise ValueError(
                f"validity bits {unfitted:#06x} set for sensors that are not installed"
            )

    def commit(self) -> None:
        """Publish the pending snapshot, advancing sequence unless frozen.

        A commit is rejected, and the published snapshot is left as it was, if the
        pending validity mask sets a bit for a sensor that is not installed. The bad
        pending value stays pending: the caller must correct it (``set_validity``
        or ``configure_node``) before a later commit or reboot can succeed.

        :raises ValueError: If a pending validity bit is set for an uninstalled sensor.
        """
        with self._lock:
            self._require_validity_installed()
            if not self._frozen:
                self._pending["snapshot_sequence"] = (
                    self._pending["snapshot_sequence"] + 1
                ) % 65536
            self._pending["uptime_seconds"] = int(self._clock() - self._boot_time)
            self._published = Snapshot(**self._pending)

    def reboot(self) -> None:
        """Simulate a node reboot: bump boot counter, reset sequence and status mailbox.

        The boot counter saturates at its u32 maximum instead of wrapping, and
        ``OVERFLOW_OR_SATURATION`` is then flagged in the module status.

        :raises ValueError: If the pending validity mask sets a bit for an uninstalled
            sensor. Checked before any state change, so a rejected reboot changes nothing.
        """
        with self._lock:
            self._require_validity_installed()
            if self._pending["boot_counter"] >= _U32_MAX:
                self._pending["boot_counter"] = _U32_MAX
                self._pending["module_status"] |= int(StatusBits.OVERFLOW_OR_SATURATION)
            else:
                self._pending["boot_counter"] += 1
            self._boot_time = self._clock()
            self._pending["uptime_seconds"] = 0
            self._pending["snapshot_sequence"] = 0
            self._pending["module_status"] |= int(StatusBits.WATCHDOG_RESET_SEEN)
            self._status_words = [0] * STATUS_COUNT
            self._status = None
            self._status_rx_ms = None
            self._status_progress_ms = None
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

    @property
    def last_status_sequence_progress_ms(self) -> int | None:
        """Clock time in ms at which the accepted ``status_sequence`` last changed.

        Set by the first valid status write after construction or
        :meth:`reboot`, and afterwards only by a valid write whose
        ``status_sequence`` differs from the previously accepted one. A
        publisher that keeps rewriting the same block therefore advances
        :attr:`last_valid_status_received_ms` but not this value. The bank
        applies no expiry; the consumer decides what is too old.
        """
        with self._lock:
            return self._status_progress_ms

    @property
    def last_rejection(self) -> str | None:
        """Short reason for the latest exception response, or None.

        Reflects only the most recent :meth:`handle_pdu` call: a call that
        returned a normal response resets it to None.
        """
        with self._lock:
            return self._last_rejection

    def handle_pdu(self, pdu: bytes) -> bytes:
        """Process one request PDU.

        :param pdu: Request PDU (function code onward, no unit id or CRC).
        :returns: Normal or exception response PDU.
        """
        with self._lock:
            self._last_rejection = None
            if not pdu:
                return self._reject(0, EXC_ILLEGAL_FUNCTION, "empty PDU")
            return self._dispatch(pdu)

    def _reject(self, fc: int, code: int, reason: str) -> bytes:
        """Record ``reason`` and build the exception response (lock held).

        :param fc: Request function code.
        :param code: Modbus exception code.
        :param reason: Short human-readable cause.
        :returns: Exception response PDU.
        """
        self._last_rejection = reason
        return _exception(fc, code)

    def _dispatch(self, pdu: bytes) -> bytes:
        fc = pdu[0]
        if fc not in (3, 4, 16):
            return self._reject(fc, EXC_ILLEGAL_FUNCTION, f"function code {fc} not supported")
        if fc in (3, 4):
            if len(pdu) != 5:
                return self._reject(
                    fc, EXC_ILLEGAL_VALUE, f"FC{fc} request length {len(pdu)}, expected 5"
                )
            addr, count = struct.unpack(">HH", pdu[1:])
            if not 1 <= count <= 125:
                return self._reject(
                    fc, EXC_ILLEGAL_VALUE, f"FC{fc} quantity {count} outside 1..125"
                )
            end = addr + count
            span = f"FC{fc} range {addr}..{end - 1}"
            if fc == 4:
                if addr < INPUT_START or end > INPUT_START + INPUT_COUNT:
                    return self._reject(
                        fc,
                        EXC_ILLEGAL_ADDRESS,
                        f"{span} outside input block "
                        f"{INPUT_START}..{INPUT_START + INPUT_COUNT - 1}",
                    )
                words = encode_snapshot(self._published)[addr - INPUT_START : end - INPUT_START]
            elif METADATA_START <= addr and end <= METADATA_START + METADATA_COUNT:
                words = self._metadata[addr - METADATA_START : end - METADATA_START]
            elif STATUS_START <= addr and end <= STATUS_START + STATUS_COUNT:
                words = self._status_words[addr - STATUS_START : end - STATUS_START]
            else:
                return self._reject(
                    fc,
                    EXC_ILLEGAL_ADDRESS,
                    f"{span} not within metadata block "
                    f"{METADATA_START}..{METADATA_START + METADATA_COUNT - 1} or status block "
                    f"{STATUS_START}..{STATUS_START + STATUS_COUNT - 1}",
                )
            return bytes([fc, 2 * len(words)]) + struct.pack(f">{len(words)}H", *words)
        # fc == 16
        if len(pdu) < 6:
            return self._reject(fc, EXC_ILLEGAL_VALUE, f"FC16 request length {len(pdu)} too short")
        addr, count, byte_count = struct.unpack(">HHB", pdu[1:6])
        if not 1 <= count <= 123 or byte_count != 2 * count or len(pdu) != 6 + byte_count:
            return self._reject(
                fc,
                EXC_ILLEGAL_VALUE,
                f"FC16 inconsistent quantity {count}, byte count {byte_count}, length {len(pdu)}",
            )
        if (addr, count) != (STATUS_START, STATUS_COUNT):
            return self._reject(
                fc,
                EXC_ILLEGAL_ADDRESS,
                f"FC16 write {addr}+{count} is not the full status block "
                f"{STATUS_START}+{STATUS_COUNT}",
            )
        values = list(struct.unpack(f">{count}H", pdu[6:]))
        try:
            validate_status(values)
        except StatusValidationError as exc:
            return self._reject(fc, EXC_ILLEGAL_VALUE, f"status block rejected: {exc}")
        now_ms = int(self._clock() * 1000)
        previous = self._status
        self._status_words = values
        self._status = decode_status(values)
        self._status_rx_ms = now_ms
        if previous is None or previous.status_sequence != self._status.status_sequence:
            self._status_progress_ms = now_ms
        return struct.pack(">BHH", 16, addr, count)
