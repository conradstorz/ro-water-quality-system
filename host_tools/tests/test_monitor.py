"""Controller-side per-node health evaluation and production permit."""

import dataclasses

from hypothesis import given
from hypothesis import strategies as st

from ro_tools.generated import registers as reg
from ro_tools.generated.registers import ValidityBits as V
from ro_tools.monitor import (
    NodeConfig,
    NodeHealth,
    critical_required,
    evaluate,
    production_permitted,
)
from ro_tools.sim.presets import RO_SKID_PROFILE, TANK_PROFILE, apply_preset
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder

RO_CFG = NodeConfig(
    1, int(reg.NodeType.RO_SKID), True, critical_required(RO_SKID_PROFILE.installed)
)
TANK_CFG = NodeConfig(2, int(reg.NodeType.TANK), True, critical_required(TANK_PROFILE.installed))


def snap(profile, preset="healthy"):
    responder = Responder(RegisterBank(), unit_id=1)
    apply_preset(responder, preset, profile)
    return responder.bank.published()


def test_critical_required_follows_what_the_node_fits():
    assert critical_required(RO_SKID_PROFILE.installed) == 0x0F
    assert critical_required(TANK_PROFILE.installed) == int(V.TANK_VOLUME)


def test_healthy_nodes_are_ok():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE)) is NodeHealth.OK
    assert evaluate(TANK_CFG, snap(TANK_PROFILE)) is NodeHealth.OK


def test_no_reply_is_missing():
    assert evaluate(RO_CFG, None) is NodeHealth.MISSING


def test_wrong_node_type_is_wrong_node():
    assert evaluate(RO_CFG, snap(TANK_PROFILE)) is NodeHealth.WRONG_NODE


def test_node_missing_a_required_sensor_is_wrong_node():
    cfg = dataclasses.replace(TANK_CFG, node_type=int(reg.NodeType.RO_SKID))
    assert evaluate(cfg, snap(RO_SKID_PROFILE)) is NodeHealth.WRONG_NODE


def test_protocol_major_mismatch_is_wrong_node():
    bad = dataclasses.replace(snap(RO_SKID_PROFILE), protocol_major=reg.PROTOCOL_MAJOR + 1)
    assert evaluate(RO_CFG, bad) is NodeHealth.WRONG_NODE


def test_invalid_critical_sensor_is_invalid():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE, "critical_sensor_invalid")) is NodeHealth.INVALID
    assert evaluate(TANK_CFG, snap(TANK_PROFILE, "critical_sensor_invalid")) is NodeHealth.INVALID


def test_old_snapshot_is_stale():
    assert evaluate(RO_CFG, snap(RO_SKID_PROFILE, "stale")) is NodeHealth.STALE


def test_age_limit_is_inclusive():
    s = snap(RO_SKID_PROFILE)
    at_limit = dataclasses.replace(s, critical_age_ms=reg.CRITICAL_MAX_AGE_MS)
    over = dataclasses.replace(s, critical_age_ms=reg.CRITICAL_MAX_AGE_MS + 1)
    assert evaluate(RO_CFG, at_limit) is NodeHealth.OK
    assert evaluate(RO_CFG, over) is NodeHealth.STALE


def test_unchanged_sequence_is_stale():
    s = snap(RO_SKID_PROFILE)
    assert evaluate(RO_CFG, s, previous_sequence=s.snapshot_sequence) is NodeHealth.STALE
    assert evaluate(RO_CFG, s, previous_sequence=s.snapshot_sequence - 1) is NodeHealth.OK


def test_optional_pressure_failure_does_not_block_a_node_that_does_not_require_it():
    s = snap(RO_SKID_PROFILE, "pressure_failed")
    assert evaluate(RO_CFG, s) is NodeHealth.OK
    needs_pressure = dataclasses.replace(
        RO_CFG, required_mask=RO_CFG.required_mask | int(V.RO_FEED_PRESSURE)
    )
    assert evaluate(needs_pressure, s) is NodeHealth.INVALID


def test_production_permitted_only_when_every_critical_node_ok():
    configs = [RO_CFG, TANK_CFG]
    both_ok = {1: NodeHealth.OK, 2: NodeHealth.OK}
    assert production_permitted(both_ok, configs) is True
    assert production_permitted({1: NodeHealth.OK}, configs) is False  # tank never reported
    assert production_permitted({1: NodeHealth.OK, 2: NodeHealth.STALE}, configs) is False


def test_production_denied_with_no_critical_node_configured():
    assert production_permitted({}, []) is False
    non_critical = dataclasses.replace(RO_CFG, critical=False)
    assert production_permitted({1: NodeHealth.OK}, [non_critical]) is False


def test_non_critical_node_failure_does_not_block():
    aux = NodeConfig(3, int(reg.NodeType.TANK), False, 0)
    results = {1: NodeHealth.OK, 2: NodeHealth.OK, 3: NodeHealth.MISSING}
    assert production_permitted(results, [RO_CFG, TANK_CFG, aux]) is True


@given(st.sampled_from([h for h in NodeHealth if h is not NodeHealth.OK]), st.sampled_from([1, 2]))
def test_any_bad_critical_node_denies_production(bad, which):
    results = {1: NodeHealth.OK, 2: NodeHealth.OK}
    results[which] = bad
    assert production_permitted(results, [RO_CFG, TANK_CFG]) is False
