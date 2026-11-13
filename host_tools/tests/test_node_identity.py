"""Node identity and the validity-subset-of-installed invariant."""

import struct

import pytest

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank

TANK_MASK = int(V.TANK_VOLUME | V.LEFT_LOAD_CELL | V.RIGHT_LOAD_CELL)


def tank_bank(extra: int = 0) -> RegisterBank:
    return RegisterBank(node_type=reg.NodeType.TANK, installed_mask=TANK_MASK | extra)


def test_default_is_full_ro_skid():
    snap = RegisterBank().published()
    assert snap.node_type == reg.NodeType.RO_SKID
    assert snap.installed_mask == ALL_SENSORS


def test_tank_identity_is_published_after_commit():
    bank = tank_bank()
    bank.commit()
    snap = bank.published()
    assert snap.node_type == int(reg.NodeType.TANK)
    assert snap.installed_mask == TANK_MASK


def test_validity_for_uninstalled_sensor_is_rejected_at_commit():
    bank = tank_bank()
    bank.set_validity(int(V.FEED_EC))
    with pytest.raises(ValueError, match="not installed"):
        bank.commit()


def test_failed_commit_leaves_previous_snapshot_published():
    bank = tank_bank()
    bank.set_validity(TANK_MASK)
    bank.commit()
    before = bank.published()
    bank.set_validity(TANK_MASK | int(V.FEED_EC))
    with pytest.raises(ValueError):
        bank.commit()
    assert bank.published() == before


def test_installed_but_failed_differs_from_not_installed():
    bank = tank_bank(extra=int(V.RO_FEED_PRESSURE))
    bank.set_validity(TANK_MASK)
    bank.commit()
    snap = bank.published()
    assert snap.installed_mask & int(V.RO_FEED_PRESSURE)
    assert not snap.validity_mask & int(V.RO_FEED_PRESSURE)


@pytest.mark.parametrize("node_type", [2, 99, -1, 65536])
def test_bad_node_type_rejected(node_type):
    with pytest.raises(ValueError):
        RegisterBank(node_type=node_type)


@pytest.mark.parametrize("mask", [0x8000, -1, 65536])
def test_bad_installed_mask_rejected(mask):
    with pytest.raises(ValueError):
        RegisterBank(installed_mask=mask)


def test_identity_readable_over_fc04():
    bank = tank_bank()
    bank.commit()
    resp = bank.handle_pdu(struct.pack(">BHH", 4, reg.ADDR_NODE_TYPE, 2))
    assert resp == bytes([4, 4]) + struct.pack(">HH", int(reg.NodeType.TANK), TANK_MASK)
