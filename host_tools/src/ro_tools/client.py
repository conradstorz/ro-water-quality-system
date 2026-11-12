"""Thin synchronous Modbus client for the sensor node (pymodbus 3.16).

This is the only non-test module that imports pymodbus. Every failure is
surfaced explicitly: transport failures raise :class:`CommsError`, Modbus
exception responses raise :class:`ModbusExceptionError`. There are no silent
retries and no cached or default data. Decoding makes no validity judgement.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Self

from pymodbus.client import ModbusSerialClient, ModbusTcpClient
from pymodbus.exceptions import ModbusException

from ro_tools.generated.registers import (
    INPUT_COUNT,
    INPUT_START,
    METADATA_COUNT,
    METADATA_LAYOUT,
    METADATA_START,
    SERIAL_BAUD,
    SERIAL_PARITY,
    SERIAL_STOP_BITS,
    STATUS_COUNT,
    STATUS_START,
    UNIT_ID,
    ControllerStatus,
    Snapshot,
    decode_snapshot,
    decode_status,
    encode_status,
)

# pymodbus logs every timeout and skipped frame itself; this module reports
# those conditions as exceptions, so the duplicate log lines are silenced.
logging.getLogger("pymodbus").setLevel(logging.CRITICAL)


class CommsError(Exception):
    """Transport failure: timeout, no response, cannot connect, connection lost."""


class ModbusExceptionError(Exception):
    """The server answered with a Modbus exception response."""

    def __init__(self, function_code: int, code: int) -> None:
        """Store the exception details.

        :param function_code: Function code of the failed request.
        :param code: Modbus exception code returned by the server.
        """
        super().__init__(f"Modbus exception {code} for function {function_code}")
        self.function_code = function_code
        self.code = code


class SensorNodeClient:
    """Reads the sensor node's snapshot and publishes controller status."""

    def __init__(self, client: ModbusTcpClient | ModbusSerialClient, unit_id: int) -> None:
        """Wrap a configured pymodbus client (use :meth:`tcp` or :meth:`serial`).

        :param client: pymodbus client built with ``retries=0``.
        :param unit_id: Modbus unit id to address.
        """
        self._client = client
        self._unit_id = unit_id

    @classmethod
    def tcp(cls, host: str, port: int, *, timeout: float = 1.0, unit_id: int = UNIT_ID) -> Self:
        """Create a Modbus-TCP client.

        :param host: Server host.
        :param port: Server port.
        :param timeout: Per-request timeout in seconds.
        :param unit_id: Modbus unit id.
        :returns: An unconnected client.
        """
        return cls(ModbusTcpClient(host, port=port, timeout=timeout, retries=0), unit_id)

    @classmethod
    def serial(
        cls,
        device: str,
        *,
        baud: int = SERIAL_BAUD,
        parity: str = SERIAL_PARITY,
        stop_bits: int = SERIAL_STOP_BITS,
        timeout: float = 1.0,
        unit_id: int = UNIT_ID,
    ) -> Self:
        """Create a Modbus-RTU serial client.

        :param device: Serial device name, e.g. ``COM5``.
        :param baud: Baud rate.
        :param parity: Parity letter.
        :param stop_bits: Stop bits.
        :param timeout: Per-request timeout in seconds.
        :param unit_id: Modbus unit id.
        :returns: An unconnected client.
        """
        return cls(
            ModbusSerialClient(
                device,
                baudrate=baud,
                bytesize=8,
                parity=parity,
                stopbits=stop_bits,
                timeout=timeout,
                retries=0,
            ),
            unit_id,
        )

    def connect(self) -> None:
        """Open the connection.

        :raises CommsError: If the connection cannot be opened.
        """
        try:
            ok = self._client.connect()
        except (ModbusException, OSError) as exc:
            raise CommsError(str(exc)) from exc
        if not ok:
            raise CommsError("could not connect")

    def close(self) -> None:
        """Close the connection."""
        self._client.close()

    def __enter__(self) -> Self:
        """Connect.

        :raises CommsError: If the connection cannot be opened.
        """
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the connection."""
        self.close()

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Issue exactly one request and map every failure to an exception.

        After any transport failure the connection is closed, so a late reply
        to the timed-out request can never be read as the next reply; the next
        call reconnects.

        :param fn: pymodbus client method to call.
        :returns: The successful pymodbus response.
        :raises CommsError: On timeout, no response or lost connection.
        :raises ModbusExceptionError: On a Modbus exception response.
        """
        try:
            if not self._client.connected and not self._client.connect():
                raise CommsError("not connected")
            rr = fn(*args, device_id=self._unit_id, **kwargs)
        except (ModbusException, OSError) as exc:
            self._client.close()
            raise CommsError(str(exc)) from exc
        except CommsError:
            self._client.close()
            raise
        if rr.isError():
            if not hasattr(rr, "exception_code"):
                self._client.close()
                raise CommsError(f"no valid response: {rr}")
            raise ModbusExceptionError(rr.function_code & 0x7F, rr.exception_code)
        return rr

    def read_snapshot(self) -> Snapshot:
        """Read the input-register snapshot with one FC04 request.

        :returns: The decoded snapshot, exactly as published (invalid data included).
        :raises CommsError: On transport failure.
        :raises ModbusExceptionError: On a Modbus exception response.
        """
        rr = self._call(self._client.read_input_registers, INPUT_START, count=INPUT_COUNT)
        return decode_snapshot(rr.registers)

    def read_metadata(self) -> dict[str, int]:
        """Read the metadata holding registers with one FC03 request.

        :returns: Metadata values keyed by the names in ``METADATA_LAYOUT``.
        :raises CommsError: On transport failure.
        :raises ModbusExceptionError: On a Modbus exception response.
        """
        rr = self._call(self._client.read_holding_registers, METADATA_START, count=METADATA_COUNT)
        return {name: rr.registers[offset] for name, _kind, offset in METADATA_LAYOUT}

    def read_status(self) -> ControllerStatus:
        """Read back the controller status block with one FC03 request.

        :returns: The decoded status.
        :raises CommsError: On transport failure.
        :raises ModbusExceptionError: On a Modbus exception response.
        """
        rr = self._call(self._client.read_holding_registers, STATUS_START, count=STATUS_COUNT)
        return decode_status(rr.registers)

    def publish_status(self, status: ControllerStatus) -> None:
        """Write the display-only controller status block with one FC16 request.

        :param status: Status to publish.
        :raises CommsError: On transport failure.
        :raises ModbusExceptionError: On a Modbus exception response.
        """
        self._call(self._client.write_registers, STATUS_START, encode_status(status))
