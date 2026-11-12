"""Tests for the responder, transports and presets (raw sockets, no pymodbus)."""

import socket
import struct
import threading
import time

import pytest

from ro_tools.generated import registers as reg
from ro_tools.sim import frames
from ro_tools.sim.presets import PRESETS, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer, serve_rtu_on

READ_BLOCK = struct.pack(">BHH", 4, 100, 40)


@pytest.fixture()
def responder() -> Responder:
    return Responder(RegisterBank())


def test_responder_answers_own_unit(responder):
    resp = responder.respond(reg.UNIT_ID, READ_BLOCK)
    assert resp is not None and resp[0] == 4 and resp[1] == 80
    assert responder.request_count == 1


def test_responder_ignores_other_unit(responder):
    assert responder.respond(2, READ_BLOCK) is None
    assert responder.request_count == 0


def test_responder_drop(responder):
    responder.drop_responses = True
    assert responder.respond(reg.UNIT_ID, READ_BLOCK) is None
    assert responder.request_count == 1


def test_responder_delay(responder):
    responder.delay_s = 0.05
    t0 = time.monotonic()
    assert responder.respond(reg.UNIT_ID, READ_BLOCK) is not None
    assert time.monotonic() - t0 >= 0.05


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    # MSG_WAITALL is unsupported on Windows (WinError 10045), so loop instead.
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        assert chunk, "connection closed early"
        data += chunk
    return data


def _exchange(sock: socket.socket, tid: int, unit: int, pdu: bytes) -> bytes:
    sock.sendall(frames.build_mbap(tid, unit, pdu))
    header = _recv_exact(sock, 7)
    rtid, length, runit = frames.parse_mbap_header(header)
    assert (rtid, runit) == (tid, unit)
    return _recv_exact(sock, length - 1)


def test_tcp_server_serves_block_and_exceptions(responder):
    with TcpSimServer(responder) as srv, socket.create_connection(srv.address, timeout=2) as sock:
        resp = _exchange(sock, 1, reg.UNIT_ID, READ_BLOCK)
        assert resp[0] == 4 and len(resp) == 82
        assert _exchange(sock, 2, reg.UNIT_ID, struct.pack(">BHH", 6, 220, 1)) == bytes(
            [0x86, 0x01]
        )
        assert _exchange(sock, 3, reg.UNIT_ID, struct.pack(">BHH", 4, 140, 1)) == bytes(
            [0x84, 0x02]
        )


def test_tcp_server_silent_for_wrong_unit_and_drop(responder):
    with TcpSimServer(responder) as srv, socket.create_connection(srv.address, timeout=0.3) as sock:
        sock.sendall(frames.build_mbap(1, 9, READ_BLOCK))
        with pytest.raises(TimeoutError):
            sock.recv(1)
        responder.drop_responses = True
        sock.sendall(frames.build_mbap(2, reg.UNIT_ID, READ_BLOCK))
        with pytest.raises(TimeoutError):
            sock.recv(1)


def test_tcp_server_stop_releases_port(responder):
    srv = TcpSimServer(responder)
    srv.start()
    addr = srv.address
    srv.stop()
    with pytest.raises(OSError):
        socket.create_connection(addr, timeout=0.3)


class FakeSerial:
    """Feeds queued chunks one byte at a time, then returns b'' (timeout)."""

    def __init__(self) -> None:
        self.rx = bytearray()
        self.tx: list[bytes] = []
        self.lock = threading.Lock()

    def feed(self, data: bytes) -> None:
        with self.lock:
            self.rx += data

    def read(self, size: int = 1) -> bytes:
        with self.lock:
            if self.rx:
                out = bytes(self.rx[:size])
                del self.rx[:size]
                return out
        time.sleep(0.005)
        return b""

    def write(self, data: bytes) -> int:
        self.tx.append(bytes(data))
        return len(data)


def _run_serial(responder: Responder, port: FakeSerial):
    stop = threading.Event()
    t = threading.Thread(target=serve_rtu_on, args=(responder, port, stop), daemon=True)
    t.start()
    return stop, t


def _wait_for(pred, timeout=2.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_serial_server_answers_valid_frame(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
        unit, pdu = frames.parse_rtu(port.tx[0])
        assert unit == reg.UNIT_ID and pdu[0] == 4 and pdu[1] == 80
    finally:
        stop.set()
        t.join(2)


def test_serial_server_ignores_bad_crc_then_recovers(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        bad = bytearray(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        bad[-1] ^= 0xFF
        port.feed(bytes(bad))
        assert not _wait_for(lambda: port.tx, timeout=0.3)
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
    finally:
        stop.set()
        t.join(2)


def test_serial_server_ignores_wrong_unit(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(7, READ_BLOCK))
        assert not _wait_for(lambda: port.tx, timeout=0.3)
    finally:
        stop.set()
        t.join(2)


def test_preset_names():
    assert PRESETS == ("healthy", "critical_sensor_invalid", "stale", "frozen_sequence", "silent")


def test_preset_healthy(responder):
    apply_preset(responder, "healthy")
    s = responder.bank.published()
    assert s.module_status & reg.StatusBits.OPERATIONAL
    assert s.validity_mask & reg.CRITICAL_VALIDITY == reg.CRITICAL_VALIDITY
    assert s.fault_mask == 0 and s.critical_age_ms < reg.CRITICAL_MAX_AGE_MS
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert not responder.drop_responses


def test_preset_critical_sensor_invalid(responder):
    apply_preset(responder, "critical_sensor_invalid")
    s = responder.bank.published()
    assert not s.validity_mask & reg.ValidityBits.PERMEATE_EC
    assert s.fault_mask & reg.FaultBits.EC_PERMEATE_FAULT


def test_preset_stale(responder):
    apply_preset(responder, "stale")
    s = responder.bank.published()
    assert s.critical_age_ms == 65535
    assert s.fault_mask & reg.FaultBits.STALE_ACQUISITION


def test_preset_frozen_sequence(responder):
    apply_preset(responder, "frozen_sequence")
    before = responder.bank.published().snapshot_sequence
    responder.bank.commit()
    assert responder.bank.published().snapshot_sequence == before


def test_preset_silent(responder):
    apply_preset(responder, "silent")
    assert responder.drop_responses is True


def test_preset_unknown(responder):
    with pytest.raises(ValueError):
        apply_preset(responder, "nope")
