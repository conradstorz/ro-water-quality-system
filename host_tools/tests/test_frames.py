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
