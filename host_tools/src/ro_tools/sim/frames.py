"""Modbus RTU and Modbus-TCP (MBAP) byte framing."""

from __future__ import annotations

import struct


class FrameError(ValueError):
    """Raised when a frame or header is malformed."""


def crc16(data: bytes) -> int:
    """Compute the Modbus CRC-16 (polynomial 0xA001, init 0xFFFF).

    :param data: Bytes to checksum.
    :returns: The 16-bit CRC as an integer.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def build_rtu(unit: int, pdu: bytes) -> bytes:
    """Build an RTU frame: unit, PDU, CRC low byte, CRC high byte.

    :param unit: Unit (slave) id.
    :param pdu: Request or response PDU.
    :returns: The complete RTU frame.
    :raises ValueError: If ``unit`` is not in 0..255.
    """
    body = bytes([unit]) + pdu
    return body + crc16(body).to_bytes(2, "little")


def parse_rtu(frame: bytes) -> tuple[int, bytes]:
    """Validate an RTU frame and split it.

    :param frame: Complete frame including CRC.
    :returns: ``(unit, pdu)``.
    :raises FrameError: If the frame is shorter than 4 bytes or the CRC mismatches.
    """
    if len(frame) < 4:
        raise FrameError(f"RTU frame too short: {len(frame)} bytes")
    if crc16(frame[:-2]) != int.from_bytes(frame[-2:], "little"):
        raise FrameError("RTU CRC mismatch")
    return frame[0], frame[1:-2]


def _request_length(buffer: bytes, start: int) -> int | None:
    """Return the expected length of the request frame starting at ``start``.

    :param buffer: Received bytes.
    :param start: Offset of the frame's unit byte.
    :returns: The total frame length, or None when the function code has no
        known request length or the header is too short to tell.
    """
    if start + 2 > len(buffer):
        return None
    function = buffer[start + 1]
    if 1 <= function <= 6:
        return 8
    if function in (15, 16):
        if start + 7 > len(buffer):
            return None
        return 9 + buffer[start + 6]
    return None


def split_rtu_requests(buffer: bytes) -> list[bytes]:
    """Split a received burst into candidate Modbus request frames.

    Lengths follow the request layouts: 8 bytes for function codes 1..6 and
    ``9 + byte_count`` for 15 and 16. A slice is accepted only if its CRC
    verifies. Anything else (unknown function code, short or corrupt slice,
    trailing garbage) is returned as one final frame holding the whole
    remainder, which then fails :func:`parse_rtu` and is discarded by callers.

    :param buffer: Bytes received without an idle gap.
    :returns: The frames in arrival order; empty for an empty buffer.
    """
    out: list[bytes] = []
    pos = 0
    while pos < len(buffer):
        length = _request_length(buffer, pos)
        end = None if length is None else pos + length
        if end is not None and end <= len(buffer):
            candidate = buffer[pos:end]
            if crc16(candidate[:-2]) == int.from_bytes(candidate[-2:], "little"):
                out.append(candidate)
                pos = end
                continue
        out.append(buffer[pos:])
        break
    return out


def build_mbap(transaction: int, unit: int, pdu: bytes) -> bytes:
    """Build a Modbus-TCP ADU (MBAP header plus PDU).

    :param transaction: Transaction id.
    :param unit: Unit id.
    :param pdu: Request or response PDU.
    :returns: The complete ADU.
    :raises struct.error: If ``transaction`` or ``unit`` is out of range.
    """
    return struct.pack(">HHHB", transaction, 0, len(pdu) + 1, unit) + pdu


def parse_mbap_header(header: bytes) -> tuple[int, int, int]:
    """Parse a 7-byte MBAP header.

    :param header: Exactly 7 header bytes.
    :returns: ``(transaction, remaining_length, unit)``; ``remaining_length``
        counts the unit byte plus the PDU.
    :raises FrameError: If the length is not 7, the protocol id is not 0, or
        the remaining length is outside 2..254.
    """
    if len(header) != 7:
        raise FrameError("MBAP header must be 7 bytes")
    transaction, protocol, length, unit = struct.unpack(">HHHB", header)
    if protocol != 0 or not 2 <= length <= 254:
        raise FrameError("invalid MBAP header")
    return transaction, length, unit
