"""pymodbus client against the hand-written simulator over loopback TCP."""

import socket
import time

import pytest

from ro_tools.client import CommsError, ModbusExceptionError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.sim.presets import apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer


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
    status = reg.ControllerStatus(
        status_sequence=9, ro_state=reg.RoState.PRODUCTION, pump_commanded=reg.PumpCommanded.ON
    )
    client.publish_status(status)
    assert client.read_status() == status
    assert responder.bank.controller_status == status


def test_publish_invalid_status_raises_illegal_value(client, responder):
    with pytest.raises(ModbusExceptionError) as exc:
        client.publish_status(reg.ControllerStatus(ro_state=8))
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
