"""Isolation invariant: name table writes never change node health or the production permit.

A rejected write, an unsupported (protocol 1.3) node and a successful write must leave the
published snapshot (input registers 100-199), :func:`evaluate`, :func:`production_permitted`
and the controller status mailbox exactly as in the no-write case.
"""

import struct

import pytest
from test_monitor import RO_CFG, TANK_CFG

from ro_tools.client import ModbusExceptionError, SensorNodeClient
from ro_tools.generated import registers as reg
from ro_tools.monitor import NodeHealth, evaluate, production_permitted
from ro_tools.onewire_names import encode_name_table
from ro_tools.sim.bus import Bus
from ro_tools.sim.presets import (
    NAMED_ENTRIES,
    NAMED_REVISION,
    RO_SKID_PROFILE,
    TANK_PROFILE,
    apply_preset,
)
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder, TcpSimServer

GOOD_STATUS = [1, 5, 4, 1, 0, 0, 0, 0]
NAMES = encode_name_table(NAMED_ENTRIES, NAMED_REVISION)
REJECTED = [2, *NAMES[1:]]  # names_schema_major != 1

READ_INPUTS = struct.pack(">BHH", 4, reg.INPUT_START, reg.INPUT_COUNT)


def _fc16(addr: int, words: list[int]) -> bytes:
    return struct.pack(">BHHB", 16, addr, len(words), 2 * len(words)) + struct.pack(
        f">{len(words)}H", *words
    )


def _fixed_clock() -> float:
    """Same time for every bank, so mailbox timestamps and uptime compare equal."""
    return 100.0


def _bus(preset: str, names_supported: bool) -> Bus:
    """Two critical nodes (RO skid on 1, tank on 2), each with a status block written."""
    bus = Bus()
    for unit, profile in ((1, RO_SKID_PROFILE), (2, TANK_PROFILE)):
        node = Responder(
            RegisterBank(clock=_fixed_clock, names_supported=names_supported), unit_id=unit
        )
        apply_preset(node, preset, profile)
        assert node.respond(unit, _fc16(reg.STATUS_START, GOOD_STATUS))[0] == 16
        bus.add(node)
    return bus


def _observe(bus: Bus) -> tuple:
    """Everything the controller (and the LCD status logic) could derive from the nodes."""
    words = {unit: bus.respond(unit, READ_INPUTS) for unit in bus.unit_ids}
    snaps = {
        unit: reg.decode_snapshot(list(struct.unpack(f">{reg.INPUT_COUNT}H", w[2:])))
        for unit, w in words.items()
    }
    configs = (RO_CFG, TANK_CFG)
    health = {c.unit_id: evaluate(c, snaps[c.unit_id]) for c in configs}
    banks = {unit: bus.node(unit).bank for unit in bus.unit_ids}
    mailbox = {
        unit: (
            b.controller_status,
            b.last_valid_status_received_ms,
            b.last_status_sequence_progress_ms,
        )
        for unit, b in banks.items()
    }
    return words, health, production_permitted(health, configs), mailbox


PRESETS_UNDER_TEST = ["healthy", "onewire_healthy", "critical_sensor_invalid", "stale"]

# (names_supported, words written to 240.., expected reply PDU prefix)
CASES = {
    "accepted": (True, NAMES, bytes([16])),
    "rejected_value": (True, REJECTED, bytes([0x90, 0x03])),
    "partial_address": (True, NAMES[:82], bytes([0x90, 0x02])),
    "unsupported_13": (False, NAMES, bytes([0x90, 0x02])),
}


@pytest.mark.parametrize("case", sorted(CASES))
@pytest.mark.parametrize("preset", PRESETS_UNDER_TEST)
def test_name_write_never_changes_health_or_permit(preset, case):
    supported, words, expected = CASES[case]
    baseline = _bus(preset, supported)
    written = _bus(preset, supported)
    for unit in written.unit_ids:
        reply = written.respond(unit, _fc16(reg.NAMES_START, words))
        assert reply is not None and reply.startswith(expected)
    assert _observe(written) == _observe(baseline)
    for b in (baseline, written):
        for unit in b.unit_ids:
            b.node(unit).bank.commit()
    assert _observe(written) == _observe(baseline)


def test_healthy_case_actually_permits_production():
    """Guard against a vacuous comparison: the healthy baseline must permit production."""
    _, health, permitted, _ = _observe(_bus("healthy", True))
    assert permitted
    assert set(health.values()) == {NodeHealth.OK}


@pytest.mark.parametrize("profile", [RO_SKID_PROFILE, TANK_PROFILE])
def test_onewire_named_snapshot_equals_onewire_healthy(profile):
    named = Responder(RegisterBank(), unit_id=1)
    plain = Responder(RegisterBank(), unit_id=1)
    apply_preset(named, "onewire_named", profile)
    apply_preset(plain, "onewire_healthy", profile)
    assert named.bank.published() == plain.bank.published()
    assert named.bank.name_table_words != plain.bank.name_table_words


@pytest.mark.parametrize("supported", [True, False])
def test_client_name_write_over_tcp_keeps_health_and_permit(supported):
    baseline = _bus("healthy", supported)
    written = _bus("healthy", supported)
    with TcpSimServer(written) as srv:
        for unit in written.unit_ids:
            with SensorNodeClient.tcp(*srv.address, timeout=0.5, unit_id=unit) as c:
                if supported:
                    c.write_name_table(NAMED_ENTRIES, NAMED_REVISION)
                    assert c.read_name_table() == (NAMED_REVISION, NAMED_ENTRIES)
                else:
                    with pytest.raises(ModbusExceptionError) as exc:
                        c.write_name_table(NAMED_ENTRIES, NAMED_REVISION)
                    assert exc.value.code == 2
    assert _observe(written) == _observe(baseline)
