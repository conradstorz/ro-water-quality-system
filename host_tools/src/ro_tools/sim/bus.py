"""Several simulated nodes sharing one RS485 bus, routed by Modbus unit id."""

from __future__ import annotations

from ro_tools.sim.server import Responder

MIN_UNIT_ID = 1
MAX_UNIT_ID = 15


class Bus:
    """A set of :class:`Responder` objects, one per unit id.

    A request for a unit that is not on the bus gets no answer, exactly like a
    missing node on the wire.
    """

    def __init__(self) -> None:
        """Create an empty bus."""
        self._nodes: dict[int, Responder] = {}

    def add(self, responder: Responder) -> None:
        """Attach a node.

        :param responder: Node to attach; its ``unit_id`` is its bus address.
        :raises ValueError: If the id is outside 1..15 or already on the bus.
        """
        unit_id = responder.unit_id
        if not MIN_UNIT_ID <= unit_id <= MAX_UNIT_ID:
            raise ValueError(f"unit id {unit_id} outside {MIN_UNIT_ID}..{MAX_UNIT_ID}")
        if unit_id in self._nodes:
            raise ValueError(f"unit id {unit_id} already on the bus")
        self._nodes[unit_id] = responder

    def node(self, unit_id: int) -> Responder:
        """Return the node with ``unit_id``.

        :param unit_id: Bus address.
        :returns: The attached responder.
        :raises KeyError: If no such node is attached.
        """
        return self._nodes[unit_id]

    @property
    def unit_ids(self) -> tuple[int, ...]:
        """Attached unit ids in ascending order."""
        return tuple(sorted(self._nodes))

    def respond(self, unit: int, pdu: bytes) -> bytes | None:
        """Route one request to its node.

        :param unit: Unit id from the frame.
        :param pdu: Request PDU.
        :returns: The node's response, or None when no node has this id or the node is silent.
        """
        node = self._nodes.get(unit)
        return None if node is None else node.respond(unit, pdu)
