"""Reference model of the main controller's per-node health logic (no I/O).

Stage C firmware must reproduce these rules. Stale, missing, mismatched or invalid
data from any critical node denies RO production (AGENTS.md rule 4).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ro_tools.generated.registers import (
    CRITICAL_MAX_AGE_MS,
    CRITICAL_VALIDITY,
    PROTOCOL_MAJOR,
    FaultBits,
    Snapshot,
    StatusBits,
)

#: Largest forward step of the u16 ``snapshot_sequence`` (modular) accepted as fresh.
MAX_SEQUENCE_FORWARD_STEP = 0x7FFF


class NodeHealth(Enum):
    """Outcome of evaluating one node's latest poll."""

    OK = "ok"
    MISSING = "missing"
    WRONG_NODE = "wrong_node"
    STALE = "stale"
    INVALID = "invalid"


@dataclass(frozen=True)
class NodeConfig:
    """What the controller expects of one node, from its own configuration.

    :ivar unit_id: Modbus unit id.
    :ivar node_type: Expected ``node_type`` register value.
    :ivar critical: Whether this node must be healthy for RO production.
    :ivar required_mask: Validity bits the controller needs from this node. Never taken
        from the node's own report.
    """

    unit_id: int
    node_type: int
    critical: bool
    required_mask: int

    def __post_init__(self) -> None:
        """Reject a critical node that requires nothing (it would always read OK).

        :raises ValueError: If ``critical`` is True and ``required_mask`` is 0.
        """
        if self.critical and self.required_mask == 0:
            raise ValueError("a critical node must require at least one validity bit")


def critical_required(installed_mask: int) -> int:
    """Return the critical validity bits that a node with ``installed_mask`` fits.

    :param installed_mask: A node's ``installed_mask`` (from its design, not a live read).
    :returns: Bit mask of critical validity bits present on that node.
    """
    return int(CRITICAL_VALIDITY) & installed_mask


def evaluate(
    config: NodeConfig,
    snapshot: Snapshot | None,
    previous_sequence: int | None = None,
    max_age_ms: int = CRITICAL_MAX_AGE_MS,
    reset_acknowledged: bool = False,
) -> NodeHealth:
    """Judge one node's latest poll.

    Precedence: MISSING, WRONG_NODE, node-reset flag, sequence, age/stale fault,
    INVALID, then OK.

    A snapshot whose ``module_status`` has ``WATCHDOG_RESET_SEEN`` is STALE until the
    controller acknowledges the reset. Recovery: re-baseline by calling this with
    ``previous_sequence=None, reset_acknowledged=True`` for the next poll, then resume
    passing the real previous sequence (with ``reset_acknowledged`` False).

    :param config: What the controller expects of this node.
    :param snapshot: The decoded snapshot, or None if the poll got no valid reply.
    :param previous_sequence: ``snapshot_sequence`` of the previous accepted poll, if any.
    :param max_age_ms: Largest acceptable ``critical_age_ms`` (inclusive).
    :param reset_acknowledged: True when the controller has acknowledged a node reset.
    :returns: The node's health; anything but OK must be treated as unusable.
    """
    if snapshot is None:
        return NodeHealth.MISSING
    if snapshot.protocol_major != PROTOCOL_MAJOR or snapshot.node_type != config.node_type:
        return NodeHealth.WRONG_NODE
    if config.required_mask & ~snapshot.installed_mask:
        return NodeHealth.WRONG_NODE
    if snapshot.module_status & int(StatusBits.WATCHDOG_RESET_SEEN) and not reset_acknowledged:
        return NodeHealth.STALE
    if previous_sequence is not None:
        delta = (snapshot.snapshot_sequence - previous_sequence) & 0xFFFF
        if not 1 <= delta <= MAX_SEQUENCE_FORWARD_STEP:
            return NodeHealth.STALE
    if snapshot.critical_age_ms > max_age_ms or snapshot.fault_mask & int(
        FaultBits.STALE_ACQUISITION
    ):
        return NodeHealth.STALE
    if config.required_mask & ~snapshot.validity_mask:
        return NodeHealth.INVALID
    return NodeHealth.OK


def production_permitted(results: Mapping[int, NodeHealth], configs: Sequence[NodeConfig]) -> bool:
    """Decide whether node health alone permits RO production.

    :param results: Latest health per unit id; a unit with no entry counts as MISSING.
    :param configs: The configured node list.
    :returns: True only if at least one critical node is configured and every critical
        node is OK. This is necessary, not sufficient: other interlocks still apply.
    """
    critical = [c for c in configs if c.critical]
    if not critical:
        return False
    return all(results.get(c.unit_id, NodeHealth.MISSING) is NodeHealth.OK for c in critical)
