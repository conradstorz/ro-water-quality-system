"""pymodbus client against the hand-written simulator over loopback TCP."""

import socket
import struct
import threading
import time

import pytest

from ro_tools.client import CommsError, ModbusExceptionError, ProtocolError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.frames import build_mbap, parse_mbap_header
from ro_tools.sim.presets import apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


def _status(**over: int) -> reg.ControllerStatus:
    """Build a status with every field explicit; ``over`` replaces defaults below."""
    values = {
        "status_schema_major": 1,
        "status_sequence": 0,
        "ro_state": reg.RoState.STANDBY,
        "pump_commanded": reg.PumpCommanded.OFF,
        "controller_fault_code": 0,
        "controller_fault_severity": 0,
        "controller_fault_count": 0,
        "controller_flags": 0,
    }
    values.update(over)
    return reg.ControllerStatus(**values)


@pytest.fixture()
def responder() -> Responder:
    r = Responder(RegisterBank())
    apply_preset(r, "healthy")
    return r


@pytest.fixture()
def server(responder):
    with TcpSimServer(responder) as srv:
        yield srv


@pytest.fixture()
def client(server):
    with SensorNodeClient.tcp(*server.address, timeout=0.5) as c:
        yield c


def test_read_snapshot(client, responder):
    s = client.read_snapshot()
    assert s == responder.bank.published()
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert s.protocol_major == reg.PROTOCOL_MAJOR


def test_snapshot_sequence_advances_between_reads(client, responder):
    first = client.read_snapshot().snapshot_sequence
    responder.bank.commit()
    assert client.read_snapshot().snapshot_sequence == (first + 1) % 65536


def test_read_metadata(client):
    assert client.read_metadata() == {
        "configuration_schema_version": 1,
        "calibration_revision": 0,
        "device_id": 1,
    }


def test_publish_and_read_back_status(client, responder):
    status = _status(
        status_sequence=9, ro_state=reg.RoState.PRODUCTION, pump_commanded=reg.PumpCommanded.ON
    )
    client.publish_status(status)
    assert client.read_status() == status
    assert responder.bank.controller_status == status


def test_publish_invalid_status_raises_illegal_value(client, responder):
    with pytest.raises(ModbusExceptionError) as exc:
        client.publish_status(_status(ro_state=8))
    assert exc.value.code == 3 and exc.value.function_code == 16
    assert responder.bank.controller_status is None


def test_invalid_sensor_data_is_returned_faithfully(client, responder):
    apply_preset(responder, "critical_sensor_invalid")
    s = client.read_snapshot()
    assert not s.validity_mask & reg.ValidityBits.PERMEATE_EC


def test_dropped_response_raises_comms_error_without_retry(client, responder):
    client.read_snapshot()
    responder.drop_responses = True
    before = responder.request_count
    t0 = time.monotonic()
    with pytest.raises(CommsError):
        client.read_snapshot()
    assert time.monotonic() - t0 < 2.0
    assert responder.request_count == before + 1, "client must not retry silently"


def test_wrong_unit_id_gets_no_reply(server):
    with (
        SensorNodeClient.tcp(*server.address, timeout=0.3, unit_id=9) as c,
        pytest.raises(CommsError),
    ):
        c.read_snapshot()


def test_connect_failure_raises_comms_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(CommsError):
        SensorNodeClient.tcp("127.0.0.1", port, timeout=0.3).connect()


def test_recovers_after_drop(client, responder):
    responder.drop_responses = True
    with pytest.raises(CommsError):
        client.read_snapshot()
    responder.drop_responses = False
    assert client.read_snapshot() == responder.bank.published()


def test_server_stopped_mid_session_raises_comms_error(responder):
    srv = TcpSimServer(responder)
    srv.start()
    c = SensorNodeClient.tcp(*srv.address, timeout=0.3)
    c.connect()
    try:
        c.read_snapshot()
        srv.stop()
        with pytest.raises(CommsError):
            c.read_snapshot()
    finally:
        c.close()


class ScriptedServer:
    """Raw-socket Modbus-TCP server that answers every request with a fixed PDU."""

    def __init__(self, reply_pdu: bytes) -> None:
        self._reply = reply_pdu
        self._listener = socket.socket()
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen()
        self.address: tuple[str, int] = self._listener.getsockname()[:2]
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def _serve(self) -> None:
        try:
            conn, _ = self._listener.accept()
        except OSError:
            return
        with conn:
            while True:
                header = self._recv(conn, 7)
                if header is None:
                    return
                transaction, length, unit = parse_mbap_header(header)
                if self._recv(conn, length - 1) is None:
                    return
                conn.sendall(build_mbap(transaction, unit, self._reply))

    @staticmethod
    def _recv(conn: socket.socket, size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            try:
                chunk = conn.recv(size - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    def __enter__(self) -> "ScriptedServer":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._listener.close()


def _words_pdu(fc: int, count: int) -> bytes:
    return bytes([fc, 2 * count]) + struct.pack(f">{count}H", *range(count))


def _scripted_client(server: ScriptedServer) -> SensorNodeClient:
    return SensorNodeClient.tcp(*server.address, timeout=0.5)


MALFORMED_REPLIES = {
    "snapshot_fc03_coded_reply": (_words_pdu(3, 40), lambda c: c.read_snapshot()),
    "snapshot_39_words": (_words_pdu(4, 39), lambda c: c.read_snapshot()),
    "snapshot_41_words": (_words_pdu(4, 41), lambda c: c.read_snapshot()),
    "metadata_8_words": (_words_pdu(3, 8), lambda c: c.read_metadata()),
    "metadata_fc04_coded_reply": (_words_pdu(4, 3), lambda c: c.read_metadata()),
    "fc16_echo_wrong_address": (
        struct.pack(">BHH", 16, reg.STATUS_START + 1, reg.STATUS_COUNT),
        lambda c: c.publish_status(_status()),
    ),
    "fc16_echo_wrong_count": (
        struct.pack(">BHH", 16, reg.STATUS_START, reg.STATUS_COUNT - 1),
        lambda c: c.publish_status(_status()),
    ),
    "fc16_reply_coded_as_fc03": (
        _words_pdu(3, 1),
        lambda c: c.publish_status(_status()),
    ),
    "exception_for_other_function": (bytes([0x83, 2]), lambda c: c.read_snapshot()),
    "status_read_exception_for_other_function": (bytes([0x84, 2]), lambda c: c.read_status()),
}


@pytest.mark.parametrize("case", sorted(MALFORMED_REPLIES))
def test_reply_that_does_not_match_request_raises_protocol_error(case):
    pdu, action = MALFORMED_REPLIES[case]
    with ScriptedServer(pdu) as srv:
        c = _scripted_client(srv)
        c.connect()
        try:
            with pytest.raises(ProtocolError):
                action(c)
        finally:
            c.close()


def test_protocol_error_is_a_comms_error():
    assert issubclass(ProtocolError, CommsError)


def test_protocol_error_closes_connection():
    with ScriptedServer(_words_pdu(4, 39)) as srv:
        c = _scripted_client(srv)
        c.connect()
        with pytest.raises(ProtocolError):
            c.read_snapshot()
        assert not c._client.connected
        c.close()


def test_exception_reports_request_function_code():
    with ScriptedServer(bytes([0x84, 2])) as srv:
        c = _scripted_client(srv)
        c.connect()
        try:
            with pytest.raises(ModbusExceptionError) as exc:
                c.read_snapshot()
        finally:
            c.close()
    assert exc.value.function_code == 4 and exc.value.code == 2


def test_read_status_never_written_is_none(client):
    assert client.read_status() is None


def test_read_status_after_reboot_is_none(client, responder):
    client.publish_status(_status(status_sequence=3))
    assert client.read_status() is not None
    responder.bank.reboot()
    assert client.read_status() is None


def test_read_status_after_valid_publish_returns_status(client):
    status = _status(status_sequence=5, ro_state=reg.RoState.PRODUCTION)
    client.publish_status(status)
    assert client.read_status() == status


def test_read_status_invalid_nonzero_block_raises_protocol_error():
    block = struct.pack(">8H", 1, 1, 99, 0, 0, 0, 0, 0)
    with ScriptedServer(bytes([3, 16]) + block) as srv:
        c = _scripted_client(srv)
        c.connect()
        try:
            with pytest.raises(ProtocolError):
                c.read_status()
        finally:
            c.close()
