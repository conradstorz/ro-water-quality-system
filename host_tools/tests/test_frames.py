"""Wire-format tests, cross-checked against pymodbus."""

import pytest
from pymodbus.framer import FramerRTU

from ro_tools.sim import frames


def test_crc_known_vector():
    # Standard published example: 01 03 00 00 00 0A -> C5 CD on the wire.
    assert frames.build_rtu(1, bytes.fromhex("0300000 00A".replace(" ", ""))) == bytes.fromhex(
        "01030000000AC5CD"
    )


def test_input_block_request_bytes():
    frame = frames.build_rtu(1, bytes([4]) + (100).to_bytes(2, "big") + (40).to_bytes(2, "big"))
    assert frame[:6] == bytes.fromhex("010400640028")  # zero-based address 100, count 40
    assert len(frame) == 8


@pytest.mark.parametrize(
    "payload", [b"\x01\x04\x00\x64\x00\x28", b"\x01\x10\x00\xdc\x00\x08\x10" + bytes(16), b"\x00"]
)
def test_crc_agrees_with_pymodbus(payload):
    # pymodbus returns the CRC already byte-swapped into wire order.
    assert frames.build_rtu(payload[0], payload[1:])[-2:] == FramerRTU.compute_CRC(
        payload
    ).to_bytes(2, "big")


def test_parse_rtu_round_trip():
    assert frames.parse_rtu(frames.build_rtu(1, b"\x04\x00\x64\x00\x28")) == (
        1,
        b"\x04\x00\x64\x00\x28",
    )


def test_parse_rtu_rejects_corrupt_crc():
    frame = bytearray(frames.build_rtu(1, b"\x04\x00\x64\x00\x28"))
    frame[3] ^= 0x01
    with pytest.raises(frames.FrameError):
        frames.parse_rtu(bytes(frame))


@pytest.mark.parametrize("frame", [b"", b"\x01", b"\x01\x04\x00"])
def test_parse_rtu_rejects_short(frame):
    with pytest.raises(frames.FrameError):
        frames.parse_rtu(frame)


def test_mbap_round_trip():
    adu = frames.build_mbap(0x1234, 1, b"\x04\x00\x64\x00\x28")
    assert adu[:7] == bytes.fromhex("12340000000601")
    assert frames.parse_mbap_header(adu[:7]) == (0x1234, 6, 1)


@pytest.mark.parametrize(
    "header",
    [
        b"\x00" * 6,
        bytes.fromhex("00010001000601"),
        bytes.fromhex("00010000000101"),
        bytes.fromhex("000100000100 01".replace(" ", "")),
    ],
)
def test_mbap_rejects_bad_header(header):
    with pytest.raises(frames.FrameError):
        frames.parse_mbap_header(header)


def _fc04(unit: int = 1, start: int = 100, count: int = 40) -> bytes:
    return frames.build_rtu(unit, bytes([4]) + start.to_bytes(2, "big") + count.to_bytes(2, "big"))


def _fc16(unit: int = 1, start: int = 220, words: int = 8) -> bytes:
    pdu = bytes([16]) + start.to_bytes(2, "big") + words.to_bytes(2, "big") + bytes([words * 2])
    return frames.build_rtu(unit, pdu + bytes(words * 2))


def test_split_single_frame():
    assert frames.split_rtu_requests(_fc04()) == [_fc04()]


def test_split_fc04_then_fc16():
    assert frames.split_rtu_requests(_fc04() + _fc16()) == [_fc04(), _fc16()]


def test_split_wrong_unit_then_addressed():
    assert frames.split_rtu_requests(_fc04(unit=7) + _fc04()) == [_fc04(unit=7), _fc04()]


@pytest.mark.parametrize("fc", [1, 2, 3, 4, 5, 6])
def test_split_fixed_length_function_codes(fc):
    frame = frames.build_rtu(1, bytes([fc, 0, 10, 0, 1]))
    assert frames.split_rtu_requests(frame + frame) == [frame, frame]


def test_split_fc15_uses_byte_count():
    frame = frames.build_rtu(1, bytes([15, 0, 0, 0, 10, 2, 0xFF, 0x03]))
    assert frames.split_rtu_requests(frame + _fc04()) == [frame, _fc04()]


def test_split_trailing_garbage_is_one_remainder():
    garbage = b"\xde\xad\xbe"
    assert frames.split_rtu_requests(_fc04() + garbage) == [_fc04(), garbage]


def test_split_garbage_only_is_one_frame():
    assert frames.split_rtu_requests(b"\xff\xff\xff\xff\xff") == [b"\xff\xff\xff\xff\xff"]


def test_split_empty_buffer():
    assert frames.split_rtu_requests(b"") == []


def test_split_truncated_fc16_is_kept_whole():
    truncated = _fc16()[:-3]
    assert frames.split_rtu_requests(truncated) == [truncated]
    assert frames.split_rtu_requests(_fc04() + truncated) == [_fc04(), truncated]


def test_split_bad_crc_is_kept_whole():
    bad = bytearray(_fc04())
    bad[-1] ^= 0xFF
    assert frames.split_rtu_requests(bytes(bad) + _fc04()) == [bytes(bad) + _fc04()]


def test_split_unknown_function_code_is_kept_whole():
    unknown = frames.build_rtu(1, bytes([0x2B, 0x0E, 0x01, 0x00]))
    assert frames.split_rtu_requests(unknown + _fc04()) == [unknown + _fc04()]


def test_split_fc16_header_cut_before_byte_count():
    short = bytes([1, 16, 0, 0xDC, 0, 8])
    assert frames.split_rtu_requests(short) == [short]
