"""Per-node simulator profiles and the pressure_failed preset."""

import pytest

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import FaultBits as F
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.sim.presets import (
    FULL_PROFILE,
    PRESETS,
    RO_SKID_PROFILE,
    TANK_PROFILE,
    apply_preset,
)
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank
from ro_tools.sim.server import Responder

RO_MASK = 0x007F
TANK_MASK = int(V.TANK_VOLUME | V.LEFT_LOAD_CELL | V.RIGHT_LOAD_CELL)


def node(profile, preset="healthy", unit_id=1):
    responder = Responder(RegisterBank(), unit_id=unit_id)
    apply_preset(responder, preset, profile)
    return responder


def test_default_profile_is_unchanged_full_node():
    snap = node(FULL_PROFILE).bank.published()
    assert snap.node_type == int(reg.NodeType.RO_SKID)
    assert snap.installed_mask == ALL_SENSORS
    assert snap.validity_mask == 0x03FF


def test_apply_preset_without_profile_matches_full_profile():
    responder = Responder(RegisterBank())
    apply_preset(responder, "healthy")
    assert responder.bank.published() == node(FULL_PROFILE).bank.published()


def test_ro_skid_healthy():
    snap = node(RO_SKID_PROFILE).bank.published()
    assert snap.node_type == int(reg.NodeType.RO_SKID)
    assert snap.installed_mask == RO_MASK
    assert snap.validity_mask == RO_MASK
    assert snap.tank_volume_gal_x100 == 0


def test_tank_healthy():
    snap = node(TANK_PROFILE, unit_id=2).bank.published()
    assert snap.node_type == int(reg.NodeType.TANK)
    assert snap.installed_mask == TANK_MASK
    assert snap.validity_mask == TANK_MASK
    assert snap.feed_ec_us_cm_x10 == 0


def test_critical_sensor_invalid_uses_the_profile_victim():
    tank = node(TANK_PROFILE, "critical_sensor_invalid", 2).bank.published()
    assert not tank.validity_mask & int(V.TANK_VOLUME)
    assert tank.fault_mask & int(F.HX711_LEFT_FAULT)
    ro = node(RO_SKID_PROFILE, "critical_sensor_invalid").bank.published()
    assert not ro.validity_mask & int(V.PERMEATE_EC)
    assert ro.fault_mask & int(F.EC_PERMEATE_FAULT)


def test_pressure_failed_is_installed_but_invalid():
    snap = node(RO_SKID_PROFILE, "pressure_failed").bank.published()
    assert snap.installed_mask & int(V.RO_FEED_PRESSURE)
    assert not snap.validity_mask & int(V.RO_FEED_PRESSURE)
    assert snap.fault_mask & int(F.PRESSURE_FAULT)


def test_pressure_failed_on_node_without_pressure_raises_and_leaves_bank_untouched():
    responder = Responder(RegisterBank(), unit_id=2)
    before = responder.bank.published()
    with pytest.raises(ValueError, match="no pressure channel"):
        apply_preset(responder, "pressure_failed", TANK_PROFILE)
    assert responder.bank.published() == before


def test_pressure_failed_is_a_listed_preset():
    assert "pressure_failed" in PRESETS
