"""Transports for the simulated sensor node: Modbus-TCP and Modbus-RTU serial."""

from __future__ import annotations

import socket
import socketserver
import threading
import time
from typing import TYPE_CHECKING, Protocol, Self

from loguru import logger

from ro_tools.generated.registers import SERIAL_BAUD, SERIAL_PARITY, SERIAL_STOP_BITS, UNIT_ID
from ro_tools.sim.frames import FrameError, build_mbap, build_rtu, parse_mbap_header, parse_rtu
from ro_tools.sim.register_bank import RegisterBank

if TYPE_CHECKING:
    import serial


class Responder:
    """Sits between a transport and the bank: unit filtering and fault injection."""

    def __init__(self, bank: RegisterBank, unit_id: int = UNIT_ID) -> None:
        """Create a responder.

        :param bank: Register bank that answers requests.
        :param unit_id: The only unit id this responder answers.
        """
        self.bank = bank
        self.unit_id = unit_id
        self.drop_responses = False
        self.delay_s = 0.0
        self.request_count = 0
        self._count_lock = threading.Lock()

    def respond(self, unit: int, pdu: bytes) -> bytes | None:
        """Answer one request.

        :param unit: Unit id from the frame.
        :param pdu: Request PDU.
        :returns: Response PDU, or None when nothing must be sent (other unit,
            a request whose function code has the 0x80 bit set, or responses
            are being dropped).
        """
        if unit != self.unit_id:
            return None
        if pdu and pdu[0] & 0x80:
            # On a 2-wire serial adapter the simulator hears its own exception
            # responses echoed back; answering them would loop.
            logger.debug("ignoring function code 0x{:02X} (exception bit set)", pdu[0])
            return None
        with self._count_lock:
            self.request_count += 1
            count = self.request_count
        if self.drop_responses:
            logger.debug("dropping response to request {}", count)
            return None
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        resp = self.bank.handle_pdu(pdu)
        if resp[0] & 0x80:
            logger.warning(
                "request function {} answered with exception {}: {}",
                pdu[0] if pdu else "none",
                resp[1],
                self.bank.last_rejection,
            )
        return resp


def _read_exact(rfile, size: int) -> bytes | None:
    data = rfile.read(size)
    return data if len(data) == size else None


class _Handler(socketserver.StreamRequestHandler):
    def setup(self) -> None:
        super().setup()
        self.server.track(self.request)  # type: ignore[attr-defined]

    def finish(self) -> None:
        self.server.untrack(self.request)  # type: ignore[attr-defined]
        super().finish()

    def handle(self) -> None:
        responder: Responder = self.server.responder  # type: ignore[attr-defined]
        try:
            while True:
                header = _read_exact(self.rfile, 7)
                if header is None:
                    return
                try:
                    transaction, length, unit = parse_mbap_header(header)
                except FrameError as exc:
                    logger.debug("closing connection: {}", exc)
                    return
                pdu = _read_exact(self.rfile, length - 1)
                if pdu is None:
                    return
                resp = responder.respond(unit, pdu)
                if resp is not None:
                    self.wfile.write(build_mbap(transaction, unit, resp))
                    self.wfile.flush()
        except OSError as exc:
            logger.debug("connection ended: {}", exc)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], responder: Responder) -> None:
        super().__init__(address, _Handler)
        self.responder = responder
        self._clients: set[socket.socket] = set()
        self._clients_lock = threading.Lock()

    def track(self, sock: socket.socket) -> None:
        with self._clients_lock:
            self._clients.add(sock)

    def untrack(self, sock: socket.socket) -> None:
        with self._clients_lock:
            self._clients.discard(sock)

    def close_clients(self) -> None:
        with self._clients_lock:
            clients = list(self._clients)
        for sock in clients:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


class TcpSimServer:
    """Threaded Modbus-TCP server bound at construction."""

    def __init__(self, responder: Responder, host: str = "127.0.0.1", port: int = 0) -> None:
        """Bind a listening socket.

        :param responder: Responder that answers requests.
        :param host: Interface to bind.
        :param port: Port to bind; 0 picks a free port.
        """
        self._server = _Server((host, port), responder)
        self._thread: threading.Thread | None = None
        self.address: tuple[str, int] = self._server.server_address[:2]

    def start(self) -> None:
        """Serve in a daemon thread."""
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join()
            self._thread = None
        self._server.server_close()
        self._server.close_clients()

    def __enter__(self) -> Self:
        """Start the server."""
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop the server."""
        self.stop()


class SerialLike(Protocol):
    """The part of a serial port the RTU loop uses."""

    def read(self, size: int = 1) -> bytes:
        """Read up to ``size`` bytes; b"" on timeout."""
        ...

    def write(self, data: bytes) -> int | None:
        """Write ``data``."""
        ...


def serve_rtu_on(responder: Responder, port: SerialLike, stop: threading.Event) -> None:
    """Run the RTU loop on an open port until ``stop`` is set.

    Frames are delimited by an idle gap (a read timeout with bytes buffered).
    Frames with a bad CRC are discarded silently.

    :param responder: Responder that answers requests.
    :param port: Open port with a short read timeout.
    :param stop: Set to end the loop.
    """
    buf = bytearray()
    while not stop.is_set():
        chunk = port.read(1)
        if chunk:
            buf += chunk
            if len(buf) > 256:
                buf.clear()
            continue
        if not buf:
            continue
        frame, buf = bytes(buf), bytearray()
        try:
            unit, pdu = parse_rtu(frame)
        except FrameError as exc:
            logger.debug("discarding frame: {}", exc)
            continue
        resp = responder.respond(unit, pdu)
        if resp is not None:
            port.write(build_rtu(unit, resp))


def open_serial_port(
    device: str,
    *,
    baud: int = SERIAL_BAUD,
    parity: str = SERIAL_PARITY,
    stop_bits: int = SERIAL_STOP_BITS,
) -> serial.Serial:
    """Open a serial device for :func:`serve_rtu_on` (8 data bits).

    The 20 ms read timeout is the idle-gap detector: longer than the 3.5
    character gap at 19200 baud, far shorter than the 1 s poll period.

    :param device: Serial device name, e.g. ``COM5``.
    :param baud: Baud rate.
    :param parity: Parity letter.
    :param stop_bits: Stop bits.
    :returns: The open port; the caller closes it.
    :raises serial.SerialException: If the device cannot be opened.
    """
    import serial

    return serial.Serial(
        device, baudrate=baud, bytesize=8, parity=parity, stopbits=stop_bits, timeout=0.02
    )
