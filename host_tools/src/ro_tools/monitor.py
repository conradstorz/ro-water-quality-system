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
from ro_tools.onewire import BusStatus, SlotReading, SlotStatus, decode_slots

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
    acknowledged_boot_counter: int | None = None,
) -> NodeHealth:
    """Judge one node's latest poll.

    Precedence: MISSING, WRONG_NODE, node-reset flag, sequence, age/stale fault,
    INVALID, then OK. Just before OK, a node is also INVALID if ``OPERATIONAL`` is clear,
    if any validity bit lies outside ``installed_mask``, or if ``CONFIGURATION_CRC_ERROR``
    is set.

    ``WATCHDOG_RESET_SEEN`` in ``module_status`` is sticky in the node, so it is
    accepted only when ``snapshot.boot_counter`` equals ``acknowledged_boot_counter``;
    otherwise the node is STALE. Recovery after a reset: the controller operator/logic
    records the node's current ``boot_counter`` as acknowledged and re-baselines by
    passing ``previous_sequence=None`` for the next poll. Thereafter it keeps passing
    the same ``acknowledged_boot_counter`` and the real previous sequence on every poll;
    the sticky flag no longer blocks. A later reboot increments ``boot_counter``, the
    acknowledgement no longer matches, and the node is STALE again. The sequence, age
    and stale-fault checks still run for an acknowledged reset.

    :param config: What the controller expects of this node.
    :param snapshot: The decoded snapshot, or None if the poll got no valid reply.
    :param previous_sequence: ``snapshot_sequence`` of the previous accepted poll, if any.
    :param max_age_ms: Largest acceptable ``critical_age_ms`` (inclusive).
    :param acknowledged_boot_counter: The ``boot_counter`` of the boot whose reset the
        controller has acknowledged, or None if none.
    :returns: The node's health; anything but OK must be treated as unusable.
    """
    if snapshot is None:
        return NodeHealth.MISSING
    if snapshot.protocol_major != PROTOCOL_MAJOR or snapshot.node_type != config.node_type:
        return NodeHealth.WRONG_NODE
    if config.required_mask & ~snapshot.installed_mask:
        return NodeHealth.WRONG_NODE
    if (
        snapshot.module_status & int(StatusBits.WATCHDOG_RESET_SEEN)
        and snapshot.boot_counter != acknowledged_boot_counter
    ):
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
    if not snapshot.module_status & int(StatusBits.OPERATIONAL):
        return NodeHealth.INVALID
    if snapshot.validity_mask & ~snapshot.installed_mask:
        return NodeHealth.INVALID  # protocol 1.2 invariant violated by the node
    if snapshot.module_status & int(StatusBits.CONFIGURATION_CRC_ERROR):
        return NodeHealth.INVALID  # calibration cannot be trusted
    return NodeHealth.OK


def production_permitted(results: Mapping[int, NodeHealth], configs: Sequence[NodeConfig]) -> bool:
    """Decide whether node health alone permits RO production.

    :param results: Latest health per unit id; a unit with no entry counts as MISSING.
    :param configs: The configured node list.
    :returns: True only if at least one critical node is configured, the union of the
        critical nodes' ``required_mask`` covers ``CRITICAL_VALIDITY`` (so, for example, an
        RO-skid-only critical list cannot permit production without tank volume), and
        every critical node is OK. This is necessary, not sufficient: other interlocks
        still apply.
    """
    critical = [c for c in configs if c.critical]
    if not critical:
        return False
    covered = 0
    for c in critical:
        covered |= c.required_mask
    if int(CRITICAL_VALIDITY) & ~covered:
        return False
    return all(results.get(c.unit_id, NodeHealth.MISSING) is NodeHealth.OK for c in critical)


class OneWireState(Enum):
    """Monitoring-only state of the 1-Wire bus; never an input to production permit."""

    OK = "ok"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OneWireBinding:
    """Binds a role name to the ROM of the device that fills it.

    :ivar role: Role name, unique within a binding list.
    :ivar rom: 64-bit ROM ID, unique within a binding list.
    """

    role: str
    rom: int


@dataclass(frozen=True)
class OneWireHealth:
    """Result of :func:`evaluate_onewire`.

    :ivar state: Overall monitoring state.
    :ivar values: Role to reading, only for usable readings.
    :ivar missing_roles: Bound roles with no usable reading (never given a default).
    :ivar unbound_roms: ROMs seen on the bus that no binding names (informational).
    :ivar reasons: Human-readable causes.
    """

    state: OneWireState
    values: Mapping[str, SlotReading]
    missing_roles: tuple[str, ...]
    unbound_roms: tuple[int, ...]
    reasons: tuple[str, ...]


_KNOWN_SLOT_BITS = sum(int(b) for b in SlotStatus)
_KNOWN_BUS_BITS = sum(int(b) for b in BusStatus)


def _slot_unusable_cause(reading: SlotReading) -> str | None:
    """:returns: Why ``reading`` cannot be used, or None if it is usable."""
    if reading.status & ~_KNOWN_SLOT_BITS:
        return "unknown status bits"
    if not reading.status & SlotStatus.PRESENT:
        return "not present"
    if reading.usable:
        return None
    names = [b.name for b in SlotStatus if reading.status & b and b.name]
    return "slot status " + "|".join(names) if names else "slot not valid"


def evaluate_onewire(snapshot: Snapshot, bindings: Sequence[OneWireBinding]) -> OneWireHealth:
    """Judge the 1-Wire block of a snapshot against configured role bindings.

    Monitoring only: this must not be called from :func:`evaluate` or
    :func:`production_permitted`, and 1-Wire state never affects the production permit.

    :param snapshot: Snapshot carrying the 1-Wire block.
    :param bindings: Role to ROM bindings.
    :returns: The 1-Wire health; an unusable role is listed missing, never defaulted.
    :raises ValueError: If a role or a ROM appears more than once in ``bindings``.
    """
    roles = [b.role for b in bindings]
    roms = [b.rom for b in bindings]
    if len(set(roles)) != len(roles):
        raise ValueError("duplicate role in bindings")
    if len(set(roms)) != len(roms):
        raise ValueError("duplicate rom in bindings")

    readings = decode_slots(snapshot)
    by_rom: dict[int, list[SlotReading]] = {}
    for reading in readings:
        by_rom.setdefault(reading.rom, []).append(reading)

    bus = snapshot.onewire_bus_status
    reasons: list[str] = []
    state = OneWireState.OK
    hard = bool(bus & (BusStatus.BUS_SHORT | BusStatus.NO_PRESENCE))
    if bus:
        state = OneWireState.DEGRADED
        names = [b.name for b in BusStatus if bus & b and b.name]
        if bus & ~_KNOWN_BUS_BITS:
            names.append("unknown")
        reasons.append("bus status " + "|".join(names))
    if snapshot.fault_mask & int(FaultBits.ONEWIRE_BUS_FAULT):
        state = OneWireState.DEGRADED
        reasons.append("ONEWIRE_BUS_FAULT fault bit set")
    if hard and bindings:
        state = OneWireState.UNAVAILABLE

    values: dict[str, SlotReading] = {}
    missing: list[str] = []
    for binding in bindings:
        found = by_rom.get(binding.rom, [])
        if hard:
            cause = "bus unavailable"
        elif not found:
            cause = "no slot for ROM"
        elif len(found) > 1:
            cause = "ROM reported in more than one slot"
        else:
            cause = _slot_unusable_cause(found[0])
        if cause is None:
            values[binding.role] = found[0]
            continue
        missing.append(binding.role)
        reasons.append(f"role {binding.role}: {cause}")
    if missing and state is OneWireState.OK:
        state = OneWireState.DEGRADED

    bound = set(roms)
    unbound = tuple(r.rom for r in readings if r.rom not in bound)
    return OneWireHealth(state, values, tuple(missing), unbound, tuple(reasons))
