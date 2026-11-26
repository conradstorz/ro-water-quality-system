"""The host-built sensor node, observed only at the Modbus RTU wire boundary."""

import re
import socket
import struct
import time

import pytest
from conftest import SENSOR_NODE_DIR

from ro_tools.client import ModbusExceptionError, SensorNodeClient
from ro_tools.sim.frames import build_rtu, parse_rtu

HOST = "127.0.0.1"


def _client(port: int, unit_id: int) -> SensorNodeClient:
    return SensorNodeClient.rtu_over_tcp(HOST, port, unit_id=unit_id)


def test_client_reads_input_block_and_metadata(run_node):
    with run_node("--id-jumpers", "1") as port, _client(port, 1) as client:
        assert client.read_snapshot().protocol_major == 1
        assert client.read_metadata() == {
            "configuration_schema_version": 1,
            "calibration_revision": 0,
            "device_id": 1,
        }


def _transact(port: int, unit_id: int, pdu: bytes) -> bytes:
    """Send one raw RTU request and return the reply PDU, bypassing the client."""
    with socket.create_connection((HOST, port), timeout=2) as sock:
        sock.sendall(build_rtu(unit_id, pdu))
        reply = sock.recv(3)
        while len(reply) < 3 or len(reply) < (5 if reply[1] & 0x80 else 5 + reply[2]):
            chunk = sock.recv(256)
            assert chunk, "connection closed mid-reply"
            reply += chunk
    unit, answer = parse_rtu(reply)
    assert unit == unit_id
    return answer


def _words(port: int, unit_id: int, address: int, count: int) -> list[int]:
    """Read raw input-register words by literal address."""
    reply = _transact(port, unit_id, struct.pack(">BHH", 4, address, count))
    assert reply[:2] == bytes([4, 2 * count])
    return list(struct.unpack(f">{count}H", reply[2:]))


def test_whole_input_block_is_one_read(run_node):
    with run_node("--id-jumpers", "1") as port:
        assert len(_words(port, 1, 100, 100)) == 100


def _assert_silent(port: int, unit_id: int) -> None:
    """A request to ``unit_id`` is answered with no bytes at all, whatever unit."""
    with socket.create_connection((HOST, port), timeout=2) as sock:
        sock.sendall(build_rtu(unit_id, struct.pack(">BHH", 4, 100, 1)))
        sock.settimeout(0.3)
        with pytest.raises(TimeoutError):
            pytest.fail(f"unit {unit_id} was answered with {sock.recv(256)!r}")


def test_late_poll_does_not_merge_two_frames(run_node):
    """The second request arrives after the gap, but before the node polls again."""
    with (
        run_node("--id-jumpers", "1", "--stall-ms", "500") as port,
        socket.create_connection((HOST, port), timeout=3) as sock,
    ):
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.sendall(build_rtu(1, struct.pack(">BHH", 4, 100, 1)))
        time.sleep(0.1)  # far longer than the frame gap, far shorter than the stall
        sock.sendall(build_rtu(1, struct.pack(">BHH", 4, 101, 1)))
        replies = b""
        while len(replies) < 14:
            chunk = sock.recv(256)
            assert chunk, "connection closed"
            replies += chunk
    assert parse_rtu(replies[:7]) == (1, b"\x04\x02\x00\x01")
    assert parse_rtu(replies[7:]) == (1, b"\x04\x02\x00\x03")


@pytest.mark.parametrize("unit_id", [5, 15])
def test_unit_id_comes_from_the_jumpers(run_node, unit_id):
    with run_node("--id-jumpers", str(unit_id)) as port:
        with _client(port, unit_id) as client:
            assert client.read_snapshot().module_status == 1
        _assert_silent(port, 1)


@pytest.mark.parametrize(
    ("args", "unit_ids"),
    [
        ((), (0, 1)),  # no link
        (("--id-jumpers", "0x11"), (1, 17)),  # out of range, not unit 1
        (("--id-jumpers", "0xFF"), (15, 255)),  # out of range, not unit 15
    ],
)
def test_node_without_a_usable_id_is_silent(run_node, args, unit_ids):
    with run_node(*args) as port:
        for unit_id in unit_ids:
            _assert_silent(port, unit_id)


def test_node_reports_protocol_1_3(run_node):
    with run_node("--id-jumpers", "1") as port:
        assert _words(port, 1, 100, 2) == [1, 3]


def test_name_table_of_protocol_1_4_is_absent(run_node):
    with run_node("--id-jumpers", "1") as port, _client(port, 1) as client:
        with pytest.raises(ModbusExceptionError) as caught:
            client.read_name_table()
        assert caught.value.code == 2


def test_node_owned_fields_replace_what_was_committed(run_node):
    """RO skid, nothing installed or valid, never fresh, no error code."""
    committed = {
        "protocol_major": 9,
        "protocol_minor": 4,
        "snapshot_sequence": 999,
        "validity_mask": 0xFFFF,
        "critical_age_ms": 0,
        "sensor_error_code": 7,
        "node_type": 1,
        "installed_mask": 0xFFFF,
    }
    args = [arg for name, value in committed.items() for arg in ("--set", f"{name}={value}")]
    with run_node("--id-jumpers", "1", *args) as port:
        assert _words(port, 1, 100, 3) == [1, 3, 1]
        assert _words(port, 1, 104, 1) == [0]  # validity_mask
        assert _words(port, 1, 106, 1) == [65535]  # critical_age_ms
        assert _words(port, 1, 128, 1) == [0]  # sensor_error_code
        assert _words(port, 1, 133, 2) == [0, 0]  # node_type, installed_mask


def test_operational_after_the_first_commit(run_node):
    with run_node("--id-jumpers", "1") as port, _client(port, 1) as client:
        snapshot = client.read_snapshot()
    assert snapshot.module_status == 0x0001
    assert snapshot.snapshot_sequence == 1


def test_not_operational_before_the_first_commit(run_node):
    with run_node("--id-jumpers", "1", "--no-commit") as port, _client(port, 1) as client:
        snapshot = client.read_snapshot()
    assert snapshot.module_status == 0
    assert snapshot.snapshot_sequence == 0
    assert (snapshot.protocol_major, snapshot.protocol_minor) == (1, 3)
    assert snapshot.critical_age_ms == 65535


def test_signed_and_32_bit_fields_round_trip(run_node):
    args = (
        "--id-jumpers", "1",
        "--set", "permeate_temp_c_x100=-1234",
        "--set", "load_left_raw=-123456",
        "--set", "permeate_total_pulses=0x12345678",
    )  # fmt: skip
    with run_node(*args) as port:
        assert _words(port, 1, 113, 1) == [0xFB2E]
        assert _words(port, 1, 117, 2) == [0xFFFE, 0x1DC0]
        assert _words(port, 1, 121, 2) == [0x1234, 0x5678]
        with _client(port, 1) as client:
            snapshot = client.read_snapshot()
    assert snapshot.permeate_temp_c_x100 == -1234
    assert snapshot.load_left_raw == -123456
    assert snapshot.permeate_total_pulses == 0x12345678


@pytest.mark.parametrize(
    ("pdu", "reply"),
    [
        (struct.pack(">BHH", 4, 99, 1), b"\x84\x02"),
        (struct.pack(">BHH", 4, 199, 2), b"\x84\x02"),
        (struct.pack(">BHH", 3, 202, 2), b"\x83\x02"),
        (struct.pack(">BHH", 4, 100, 126), b"\x84\x03"),
        (struct.pack(">BHH", 6, 200, 1), b"\x86\x01"),
    ],
)
def test_requests_outside_the_served_blocks_get_exceptions(run_node, pdu, reply):
    with run_node("--id-jumpers", "1") as port:
        assert _transact(port, 1, pdu) == reply


def test_node_logic_includes_no_platform_headers():
    """Hardware is reached only through the interfaces in ro_hal.hpp."""
    sources = [
        path
        for root in (SENSOR_NODE_DIR / "lib", SENSOR_NODE_DIR.parent / "lib")
        for path in root.rglob("*.[ch]pp")
    ]
    assert len(sources) >= 6
    allowed = re.compile(r"<(cstddef|cstdint|cstring)>|\"ro_[a-z_]+\.hpp\"")
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#include"):
                assert allowed.search(line), f"{path.name}: {line}"
