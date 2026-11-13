"""Tests for the responder, transports and presets (raw sockets, no pymodbus)."""

import socket
import struct
import threading
import time

import pytest
from loguru import logger

from ro_tools.generated import registers as reg
from ro_tools.sim import frames
from ro_tools.sim.presets import PRESETS, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer, open_serial_port, serve_rtu_on

READ_BLOCK = struct.pack(">BHH", 4, 100, reg.INPUT_COUNT)


@pytest.fixture()
def responder() -> Responder:
    return Responder(RegisterBank())


def test_responder_answers_own_unit(responder):
    resp = responder.respond(reg.UNIT_ID, READ_BLOCK)
    assert resp is not None and resp[0] == 4 and resp[1] == 2 * reg.INPUT_COUNT
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


@pytest.fixture()
def log_lines():
    """Collect Loguru messages (all levels) emitted during a test."""
    lines: list[tuple[str, str]] = []
    handler = logger.add(
        lambda m: lines.append((m.record["level"].name, m.record["message"])), level="DEBUG"
    )
    yield lines
    logger.remove(handler)


@pytest.mark.parametrize("fc", [0x84, 0x90, 0x80, 0xFF])
def test_responder_ignores_request_with_exception_bit(responder, fc, log_lines):
    assert responder.respond(reg.UNIT_ID, bytes([fc, 2])) is None
    assert any(level == "DEBUG" for level, _ in log_lines)
    assert not any(level == "WARNING" for level, _ in log_lines)


def test_responder_logs_warning_for_exception_response(responder, log_lines):
    bad = struct.pack(">BHH", 4, 100, 101)
    resp = responder.respond(reg.UNIT_ID, bad)
    assert resp == bytes([0x84, 2])
    warnings = [m for level, m in log_lines if level == "WARNING"]
    assert len(warnings) == 1
    assert "4" in warnings[0] and "exception 2" in warnings[0]
    assert "100..200" in warnings[0], "bank.last_rejection text must be included"


def test_responder_does_not_warn_for_normal_response(responder, log_lines):
    assert responder.respond(reg.UNIT_ID, READ_BLOCK) is not None
    assert not any(level == "WARNING" for level, _ in log_lines)


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
        assert resp[0] == 4 and len(resp) == 202
        assert _exchange(sock, 2, reg.UNIT_ID, struct.pack(">BHH", 6, 220, 1)) == bytes(
            [0x86, 0x01]
        )
        assert _exchange(sock, 3, reg.UNIT_ID, struct.pack(">BHH", 4, 200, 1)) == bytes(
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
        assert unit == reg.UNIT_ID and pdu[0] == 4 and pdu[1] == 2 * reg.INPUT_COUNT
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
    assert PRESETS == (
        "healthy",
        "critical_sensor_invalid",
        "stale",
        "frozen_sequence",
        "silent",
        "pressure_failed",
    )


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


def test_tcp_server_survives_client_reset_quietly(responder, capfd):
    import struct as _s

    with TcpSimServer(responder) as srv:
        s = socket.create_connection(srv.address)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, _s.pack("ii", 1, 0))
        responder.delay_s = 0.2
        s.sendall(frames.build_mbap(1, reg.UNIT_ID, READ_BLOCK))
        time.sleep(0.05)
        s.close()  # RST while the handler is about to write
        time.sleep(0.4)
    assert "Traceback" not in capfd.readouterr().err


def test_request_count_is_exact_under_concurrency(responder):
    def hammer() -> None:
        for _ in range(2000):
            responder.respond(reg.UNIT_ID, READ_BLOCK)

    threads = [threading.Thread(target=hammer) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert responder.request_count == 16000


def test_stop_closes_accepted_connections_and_is_idempotent(responder, capfd):
    srv = TcpSimServer(responder)
    srv.start()
    s = socket.create_connection(srv.address)
    s.settimeout(1)
    s.sendall(frames.build_mbap(1, reg.UNIT_ID, READ_BLOCK))
    assert len(s.recv(512)) > 0
    srv.stop()
    srv.stop()
    try:
        s.sendall(frames.build_mbap(2, reg.UNIT_ID, READ_BLOCK))
        data = s.recv(512)
    except OSError:
        data = b""
    s.close()
    assert data == b""
    time.sleep(0.1)
    assert "Traceback" not in capfd.readouterr().err


def test_open_serial_port_uses_protocol_settings(monkeypatch):
    import serial

    calls = []

    class FakePort:
        def __init__(self, *args, **kwargs):
            calls.append((args, kwargs))

    monkeypatch.setattr(serial, "Serial", FakePort)
    port = open_serial_port("COM7")
    assert isinstance(port, FakePort)
    assert calls == [
        (
            ("COM7",),
            {
                "baudrate": reg.SERIAL_BAUD,
                "bytesize": 8,
                "parity": reg.SERIAL_PARITY,
                "stopbits": reg.SERIAL_STOP_BITS,
                "timeout": 0.02,
            },
        )
    ]


def test_open_serial_port_overrides(monkeypatch):
    import serial

    calls = []
    monkeypatch.setattr(serial, "Serial", lambda *a, **k: calls.append(k))
    open_serial_port("COM7", baud=9600, parity="N", stop_bits=2)
    assert (calls[0]["baudrate"], calls[0]["parity"], calls[0]["stopbits"]) == (9600, "N", 2)


class EchoSerial(FakeSerial):
    """A 2-wire adapter: every transmitted frame is heard again on receive."""

    def write(self, data: bytes) -> int:
        self.feed(bytes(data))
        return super().write(data)


def _other_block() -> bytes:
    return struct.pack(">BHH", 4, 100, 2)


def test_serial_server_does_not_answer_its_own_echo(responder):
    port = EchoSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
        time.sleep(0.2)  # echo has come back and been through an idle gap
        assert len(port.tx) == 1
        assert port.tx[0][1] == 4
        assert responder.request_count == 1
    finally:
        stop.set()
        t.join(2)


def test_serial_server_answers_different_request_after_echo(responder):
    port = EchoSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: len(port.tx) == 1)
        time.sleep(0.1)
        port.feed(frames.build_rtu(reg.UNIT_ID, _other_block()))
        assert _wait_for(lambda: len(port.tx) == 2)
        time.sleep(0.1)
        assert len(port.tx) == 2
        assert frames.parse_rtu(port.tx[1])[1][:2] == bytes([4, 4])
    finally:
        stop.set()
        t.join(2)


def test_serial_server_answers_identical_request_twice_with_echo(responder):
    port = EchoSerial()
    stop, t = _run_serial(responder, port)
    try:
        for expected in (1, 2):
            port.feed(frames.build_rtu(reg.UNIT_ID, _other_block()))
            assert _wait_for(lambda n=expected: len(port.tx) == n)
            time.sleep(0.1)
        assert len(port.tx) == 2
        assert responder.request_count == 2
    finally:
        stop.set()
        t.join(2)


def test_serial_server_handles_echo_merged_with_next_request(responder):
    port = EchoSerial()
    stop, t = _run_serial(responder, port)
    try:
        req = frames.build_rtu(reg.UNIT_ID, _other_block())
        port.feed(req)
        assert _wait_for(lambda: len(port.tx) == 1)
        port.feed(frames.build_rtu(reg.UNIT_ID, READ_BLOCK))  # may land right behind the echo
        assert _wait_for(lambda: len(port.tx) == 2)
        time.sleep(0.2)
        assert len(port.tx) == 2
    finally:
        stop.set()
        t.join(2)


def test_serial_server_answers_back_to_back_requests_in_order(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(
            frames.build_rtu(reg.UNIT_ID, _other_block())
            + frames.build_rtu(reg.UNIT_ID, READ_BLOCK)
        )
        assert _wait_for(lambda: len(port.tx) == 2)
        assert [len(frames.parse_rtu(f)[1]) for f in port.tx] == [6, 202]
    finally:
        stop.set()
        t.join(2)


def test_serial_server_wrong_unit_then_addressed_gives_one_response(responder):
    port = FakeSerial()
    stop, t = _run_serial(responder, port)
    try:
        port.feed(frames.build_rtu(7, READ_BLOCK) + frames.build_rtu(reg.UNIT_ID, READ_BLOCK))
        assert _wait_for(lambda: port.tx)
        time.sleep(0.2)
        assert len(port.tx) == 1
        assert frames.parse_rtu(port.tx[0])[0] == reg.UNIT_ID
    finally:
        stop.set()
        t.join(2)
