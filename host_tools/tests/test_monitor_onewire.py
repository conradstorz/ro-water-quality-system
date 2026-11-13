"""1-Wire health is monitoring only and never influences the production permit."""

import dataclasses
import inspect

import pytest
from test_monitor import RO_CFG, TANK_CFG, snap

from ro_tools import monitor
from ro_tools.generated import registers as reg
from ro_tools.monitor import (
    OneWireBinding,
    OneWireHealth,
    OneWireState,
    evaluate,
    evaluate_onewire,
    production_permitted,
)
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    NO_BUS_STATUS,
    BusStatus,
    OneWireDevice,
    encode_onewire,
    make_rom,
)
from ro_tools.sim.presets import FULL_PROFILE, RO_SKID_PROFILE, TANK_PROFILE

ROM_A = make_rom(FAMILY_DS18B20, 0x1001)
ROM_B = make_rom(FAMILY_DS2438, 0x1002)
ROM_C = make_rom(FAMILY_DS18B20, 0x1003)
BIND_A = OneWireBinding("tank_temp", ROM_A)
BIND_B = OneWireBinding("feed_temp", ROM_B)
MAX_AGE = 1000  # test-local value; the real limit is controller config (TBD)


def with_bus(devices, bus_status=NO_BUS_STATUS, **changes):
    base = snap(FULL_PROFILE)
    fields = encode_onewire(devices, bus_status) | changes
    return dataclasses.replace(base, **fields)


def dev(rom, **kw):
    return OneWireDevice(rom, primary=2150, secondary=0, **kw)


def test_healthy_bound_devices_ok():
    h = evaluate_onewire(with_bus([dev(ROM_A), dev(ROM_B)]), [BIND_A, BIND_B], max_age_ms=MAX_AGE)
    assert isinstance(h, OneWireHealth)
    assert h.state is OneWireState.OK
    assert set(h.values) == {"tank_temp", "feed_temp"}
    assert h.values["tank_temp"].primary == 2150
    assert h.missing_roles == () and h.unbound_roms == () and h.reasons == ()


def test_no_bindings_no_devices_ok():
    h = evaluate_onewire(with_bus([]), [], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.OK
    assert not h.values and not h.reasons


def test_bound_rom_without_slot_is_missing_and_degraded():
    h = evaluate_onewire(with_bus([dev(ROM_A)]), [BIND_A, BIND_B], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED
    assert h.missing_roles == ("feed_temp",)
    assert "feed_temp" not in h.values
    assert any("feed_temp" in r for r in h.reasons)


@pytest.mark.parametrize(
    "kw",
    [{"stale": True}, {"crc_error": True}, {"valid": False}, {"present": False, "missing": True}],
)
def test_unusable_slot_is_missing_with_no_value(kw):
    h = evaluate_onewire(
        with_bus([dev(ROM_A, **kw), dev(ROM_B)]), [BIND_A, BIND_B], max_age_ms=MAX_AGE
    )
    assert h.state is OneWireState.DEGRADED
    assert h.missing_roles == ("tank_temp",)
    assert "tank_temp" not in h.values
    assert "feed_temp" in h.values
    assert any("tank_temp" in r for r in h.reasons)


def test_unsupported_family_bound_is_missing():
    rom = make_rom(0x10, 0x55)
    h = evaluate_onewire(with_bus([dev(rom)]), [OneWireBinding("odd", rom)], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED
    assert h.missing_roles == ("odd",)
    assert not h.values


def test_unbound_roms_informational_state_unaffected():
    h = evaluate_onewire(with_bus([dev(ROM_A), dev(ROM_C)]), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.OK
    assert h.unbound_roms == (ROM_C,)
    assert h.reasons == ()


def test_no_bindings_with_devices_ok_and_unbound():
    h = evaluate_onewire(with_bus([dev(ROM_A)]), [], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.OK
    assert h.unbound_roms == (ROM_A,)


@pytest.mark.parametrize("bit", [BusStatus.CRC_ERRORS, BusStatus.OVERFLOW])
def test_soft_bus_bits_degrade(bit):
    h = evaluate_onewire(with_bus([dev(ROM_A)], bit), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED
    assert h.reasons


@pytest.mark.parametrize("bit", [BusStatus.BUS_SHORT, BusStatus.NO_PRESENCE])
def test_hard_bus_bits_with_bindings_are_unavailable(bit):
    h = evaluate_onewire(with_bus([dev(ROM_A)], bit), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.UNAVAILABLE
    assert not h.values
    assert h.missing_roles == ("tank_temp",)


@pytest.mark.parametrize("bit", [BusStatus.BUS_SHORT, BusStatus.NO_PRESENCE])
def test_hard_bus_bits_without_bindings_degrade_only(bit):
    h = evaluate_onewire(with_bus([], bit), [], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED


def test_fault_bit_10_degrades():
    fault = int(reg.FaultBits.ONEWIRE_BUS_FAULT)
    assert fault == 1 << 10
    h = evaluate_onewire(with_bus([dev(ROM_A)], fault_mask=fault), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED
    assert any("fault" in r.lower() for r in h.reasons)


def test_duplicate_role_or_rom_raises():
    with pytest.raises(ValueError):
        evaluate_onewire(
            with_bus([]), [BIND_A, OneWireBinding("tank_temp", ROM_B)], max_age_ms=MAX_AGE
        )
    with pytest.raises(ValueError):
        evaluate_onewire(with_bus([]), [BIND_A, OneWireBinding("other", ROM_A)], max_age_ms=MAX_AGE)


def test_garbage_words_never_yield_values():
    base = snap(FULL_PROFILE)
    fields = {k: 0xFFFF for k in encode_onewire([])}
    h = evaluate_onewire(dataclasses.replace(base, **fields), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.UNAVAILABLE
    assert not h.values


def test_duplicate_rom_in_slots_is_not_trusted():
    base = snap(FULL_PROFILE)
    fields = encode_onewire([dev(ROM_A)])
    for w in range(4):
        fields[f"onewire_s1_rom{w}"] = fields[f"onewire_s0_rom{w}"]
    for f in ("primary", "secondary", "status"):
        fields[f"onewire_s1_{f}"] = fields[f"onewire_s0_{f}"]
    h = evaluate_onewire(dataclasses.replace(base, **fields), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED
    assert "tank_temp" not in h.values


def test_max_age_is_required_keyword_only():
    with pytest.raises(TypeError):
        evaluate_onewire(with_bus([]), [])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        evaluate_onewire(with_bus([]), [], MAX_AGE)  # type: ignore[misc]


def test_age_at_limit_ok_over_limit_unavailable():
    at = evaluate_onewire(
        with_bus([dev(ROM_A)], onewire_age_ms=MAX_AGE), [BIND_A], max_age_ms=MAX_AGE
    )
    assert at.state is OneWireState.OK and "tank_temp" in at.values
    over = evaluate_onewire(
        with_bus([dev(ROM_A)], onewire_age_ms=MAX_AGE + 1), [BIND_A], max_age_ms=MAX_AGE
    )
    assert over.state is OneWireState.UNAVAILABLE
    assert not over.values and over.missing_roles == ("tank_temp",)
    assert any("stale" in r for r in over.reasons)


def _assert_untrusted(h, reason_part):
    assert h.state is OneWireState.DEGRADED
    assert not h.values
    assert h.missing_roles == ("tank_temp", "feed_temp")
    assert any(reason_part in r for r in h.reasons)


def test_device_count_mismatch_is_inconsistent():
    s = with_bus([dev(ROM_A), dev(ROM_B)], onewire_device_count=1)
    _assert_untrusted(evaluate_onewire(s, [BIND_A, BIND_B], max_age_ms=MAX_AGE), "device count")


def test_unsorted_slots_are_inconsistent():
    fields = encode_onewire([dev(ROM_A), dev(ROM_B)])
    for f in ("rom0", "rom1", "rom2", "rom3", "primary", "secondary", "status"):
        a, b = fields[f"onewire_s0_{f}"], fields[f"onewire_s1_{f}"]
        fields[f"onewire_s0_{f}"], fields[f"onewire_s1_{f}"] = b, a
    s = dataclasses.replace(snap(FULL_PROFILE), **fields)
    _assert_untrusted(evaluate_onewire(s, [BIND_A, BIND_B], max_age_ms=MAX_AGE), "sorted")


def test_rom_crc_failure_is_inconsistent():
    fields = encode_onewire([dev(ROM_A), dev(ROM_B)])
    fields["onewire_s0_rom0"] ^= 0x0100  # flip a CRC bit
    s = dataclasses.replace(snap(FULL_PROFILE), **fields)
    h = evaluate_onewire(s, [BIND_A, BIND_B], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.DEGRADED and not h.values
    assert any("CRC" in r for r in h.reasons)


def test_empty_slots_skip_crc_check():
    h = evaluate_onewire(with_bus([dev(ROM_A)]), [BIND_A], max_age_ms=MAX_AGE)
    assert h.state is OneWireState.OK


def _words():
    healthy = [dev(ROM_A), dev(ROM_B)]
    return {
        "healthy": encode_onewire(healthy),
        "lost": encode_onewire([], BusStatus.NO_PRESENCE),
        "crc": encode_onewire([dev(ROM_A, crc_error=True)], BusStatus.CRC_ERRORS),
        "overflow": encode_onewire(
            [dev(make_rom(FAMILY_DS18B20, n)) for n in range(1, 12)], BusStatus(0)
        ),
        "garbage": {k: 0xFFFF for k in encode_onewire([])},
    }


def test_production_permit_invariant_under_onewire_state():
    configs = [RO_CFG, TANK_CFG]
    results = {}
    for name, fields in _words().items():
        for fault in (0, int(reg.FaultBits.ONEWIRE_BUS_FAULT)):
            ro = dataclasses.replace(snap(RO_SKID_PROFILE), **fields, fault_mask=fault)
            tank = dataclasses.replace(snap(TANK_PROFILE), **fields, fault_mask=fault)
            health = {1: evaluate(RO_CFG, ro), 2: evaluate(TANK_CFG, tank)}
            results[(name, fault)] = (health, production_permitted(health, configs))
    first = next(iter(results.values()))
    assert first[1] is True
    assert all(v == first for v in results.values())


def test_evaluate_and_permit_do_not_reference_onewire():
    for fn in (monitor.evaluate, monitor.production_permitted):
        assert "onewire" not in inspect.getsource(fn).lower()
