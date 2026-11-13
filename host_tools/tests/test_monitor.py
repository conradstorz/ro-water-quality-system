"""Controller-side per-node health evaluation and production permit."""

import dataclasses

import pytest
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
from ro_tools.sim.presets import FULL_PROFILE, RO_SKID_PROFILE, TANK_PROFILE, apply_preset
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


def with_seq(seq, **changes):
    return dataclasses.replace(snap(RO_SKID_PROFILE), snapshot_sequence=seq, **changes)


def test_unchanged_sequence_is_stale():
    s = with_seq(100)
    assert evaluate(RO_CFG, s, previous_sequence=100) is NodeHealth.STALE


def test_forward_step_is_ok():
    assert evaluate(RO_CFG, with_seq(101), previous_sequence=100) is NodeHealth.OK


def test_sequence_wrap_is_ok():
    assert evaluate(RO_CFG, with_seq(0), previous_sequence=0xFFFF) is NodeHealth.OK


def test_backward_step_is_stale():
    assert evaluate(RO_CFG, with_seq(99), previous_sequence=100) is NodeHealth.STALE
    assert evaluate(RO_CFG, with_seq(0), previous_sequence=500) is NodeHealth.STALE


def test_forward_step_limit():
    assert evaluate(RO_CFG, with_seq(0x7FFF), previous_sequence=0) is NodeHealth.OK
    assert evaluate(RO_CFG, with_seq(0x8000), previous_sequence=0) is NodeHealth.STALE


RESET = int(reg.StatusBits.WATCHDOG_RESET_SEEN)


def flagged(seq, boot=3, **changes):
    return with_seq(
        seq, module_status=RESET | int(reg.StatusBits.OPERATIONAL), boot_counter=boot, **changes
    )


def test_watchdog_reset_flag_is_stale_until_acknowledged():
    s = flagged(5)
    assert evaluate(RO_CFG, s) is NodeHealth.STALE
    assert evaluate(RO_CFG, s, previous_sequence=4) is NodeHealth.STALE
    assert evaluate(RO_CFG, s, previous_sequence=None, acknowledged_boot_counter=3) is (
        NodeHealth.OK
    )


def test_acknowledged_boot_with_sticky_flag_stays_ok_across_polls():
    assert evaluate(RO_CFG, flagged(5), None, acknowledged_boot_counter=3) is NodeHealth.OK
    for prev, seq in [(5, 6), (6, 7), (7, 9), (9, 10)]:
        result = evaluate(RO_CFG, flagged(seq), prev, acknowledged_boot_counter=3)
        assert result is NodeHealth.OK


def test_second_reboot_is_stale_even_with_earlier_ack():
    s = flagged(8, boot=4)
    assert evaluate(RO_CFG, s, 7, acknowledged_boot_counter=3) is NodeHealth.STALE
    assert evaluate(RO_CFG, s, 7, acknowledged_boot_counter=None) is NodeHealth.STALE


def test_acknowledged_reset_does_not_mask_age_fault_or_sequence():
    over = reg.CRITICAL_MAX_AGE_MS + 1
    old = flagged(6, critical_age_ms=over)
    assert evaluate(RO_CFG, old, 5, acknowledged_boot_counter=3) is NodeHealth.STALE
    fault = int(reg.FaultBits.STALE_ACQUISITION)
    s = flagged(6, fault_mask=fault, critical_age_ms=0)
    assert evaluate(RO_CFG, s, 5, acknowledged_boot_counter=3) is NodeHealth.STALE
    assert evaluate(RO_CFG, flagged(5), 5, acknowledged_boot_counter=3) is NodeHealth.STALE


def test_acknowledged_reset_delta_0xffff_is_stale():
    s = flagged(4)
    assert evaluate(RO_CFG, s, previous_sequence=5, acknowledged_boot_counter=3) is (
        NodeHealth.STALE
    )


def test_stale_acquisition_fault_alone_is_stale():
    s = with_seq(1, fault_mask=int(reg.FaultBits.STALE_ACQUISITION), critical_age_ms=0)
    assert evaluate(RO_CFG, s) is NodeHealth.STALE


def test_precedence_stale_over_invalid():
    s = snap(RO_SKID_PROFILE, "critical_sensor_invalid")
    s = dataclasses.replace(s, critical_age_ms=reg.CRITICAL_MAX_AGE_MS + 1)
    assert evaluate(RO_CFG, s) is NodeHealth.STALE


def test_precedence_wrong_node_over_stale():
    s = dataclasses.replace(snap(TANK_PROFILE), critical_age_ms=reg.CRITICAL_MAX_AGE_MS + 1)
    assert evaluate(RO_CFG, s) is NodeHealth.WRONG_NODE
    flagged = dataclasses.replace(s, module_status=int(reg.StatusBits.WATCHDOG_RESET_SEEN))
    assert evaluate(RO_CFG, flagged, previous_sequence=flagged.snapshot_sequence) is (
        NodeHealth.WRONG_NODE
    )


def test_critical_node_requiring_nothing_is_rejected():
    with pytest.raises(ValueError):
        NodeConfig(9, int(reg.NodeType.TANK), True, 0)
    NodeConfig(9, int(reg.NodeType.TANK), False, 0)


def test_optional_pressure_failure_does_not_block_a_node_that_does_not_require_it():
    s = snap(RO_SKID_PROFILE, "pressure_failed")
    assert evaluate(RO_CFG, s) is NodeHealth.OK
    needs_pressure = dataclasses.replace(
        RO_CFG, required_mask=RO_CFG.required_mask | int(V.RO_FEED_PRESSURE)
    )
    assert evaluate(needs_pressure, s) is NodeHealth.INVALID


def test_non_operational_node_is_invalid():
    s = snap(RO_SKID_PROFILE)
    off = dataclasses.replace(s, module_status=s.module_status & ~int(reg.StatusBits.OPERATIONAL))
    assert evaluate(RO_CFG, off) is NodeHealth.INVALID


def test_validity_outside_installed_is_invalid():
    s = snap(TANK_PROFILE)
    bad = dataclasses.replace(s, validity_mask=s.validity_mask | int(V.RO_FEED_PRESSURE))
    assert bad.validity_mask & ~bad.installed_mask
    assert evaluate(TANK_CFG, bad) is NodeHealth.INVALID


def test_configuration_crc_error_is_invalid():
    s = snap(RO_SKID_PROFILE)
    bad = dataclasses.replace(
        s, module_status=s.module_status | int(reg.StatusBits.CONFIGURATION_CRC_ERROR)
    )
    assert evaluate(RO_CFG, bad) is NodeHealth.INVALID


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


def test_ro_only_critical_cannot_permit_production():
    assert production_permitted({1: NodeHealth.OK}, [RO_CFG]) is False


def test_single_full_profile_node_covers_critical_validity():
    cfg = NodeConfig(1, int(reg.NodeType.RO_SKID), True, critical_required(FULL_PROFILE.installed))
    assert production_permitted({1: NodeHealth.OK}, [cfg]) is True


def test_non_critical_node_failure_does_not_block():
    aux = NodeConfig(3, int(reg.NodeType.TANK), False, 0)
    results = {1: NodeHealth.OK, 2: NodeHealth.OK, 3: NodeHealth.MISSING}
    assert production_permitted(results, [RO_CFG, TANK_CFG, aux]) is True


@given(st.sampled_from([h for h in NodeHealth if h is not NodeHealth.OK]), st.sampled_from([1, 2]))
def test_any_bad_critical_node_denies_production(bad, which):
    results = {1: NodeHealth.OK, 2: NodeHealth.OK}
    results[which] = bad
    assert production_permitted(results, [RO_CFG, TANK_CFG]) is False
