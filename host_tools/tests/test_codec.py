"""Tests for the generated register codec."""

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ro_tools.generated import registers as reg


def _field_strategy():
    return st.fixed_dictionaries(
        {name: st.integers(*reg.TYPE_RANGES[typ]) for name, typ, _ in reg.SNAPSHOT_LAYOUT}
    )


@given(_field_strategy())
def test_snapshot_round_trip(fields):
    s = reg.Snapshot(**fields)
    words = reg.encode_snapshot(s)
    assert len(words) == reg.INPUT_COUNT
    assert all(0 <= w <= 0xFFFF for w in words)
    assert reg.decode_snapshot(words) == s


def test_constants_match_map():
    assert (reg.INPUT_START, reg.INPUT_COUNT) == (100, 100)
    assert (reg.STATUS_START, reg.STATUS_COUNT) == (220, 8)
    assert reg.ADDR_FEED_EC_US_CM_X10 == 109
    assert reg.ADDR_RESERVED_139 == 139
    assert reg.SERIAL_PARITY == "E"
    assert int(reg.CRITICAL_VALIDITY) == 0x008F
    assert reg.RoState.PRODUCTION == 4
    assert reg.PumpCommanded.ON == 1
    assert reg.FaultSeverity.CRITICAL == 3
    assert reg.FAULT_CODES[4001].state_dependent is True
    assert reg.FAULT_CODES[1001].default_severity is reg.FaultSeverity.CRITICAL


def test_u32_is_high_word_first():
    words = reg.encode_snapshot(reg.Snapshot(uptime_seconds=0x12345678))
    off = reg.ADDR_UPTIME_SECONDS - reg.INPUT_START
    assert words[off : off + 2] == [0x1234, 0x5678]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-32768, 0x8000), (-1, 0xFFFF), (0, 0), (32767, 0x7FFF)],
)
def test_i16_twos_complement(value, expected):
    words = reg.encode_snapshot(reg.Snapshot(permeate_temp_c_x100=value))
    off = reg.ADDR_PERMEATE_TEMP_C_X100 - reg.INPUT_START
    assert words[off] == expected
    assert reg.decode_snapshot(words).permeate_temp_c_x100 == value


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-2147483648, [0x8000, 0]),
        (-1, [0xFFFF, 0xFFFF]),
        (0, [0, 0]),
        (2147483647, [0x7FFF, 0xFFFF]),
    ],
)
def test_i32_twos_complement(value, expected):
    words = reg.encode_snapshot(reg.Snapshot(load_left_raw=value))
    off = reg.ADDR_LOAD_LEFT_RAW - reg.INPUT_START
    assert words[off : off + 2] == expected
    assert reg.decode_snapshot(words).load_left_raw == value


@pytest.mark.parametrize(
    "kwargs",
    [
        {"module_status": 65536},
        {"module_status": -1},
        {"permeate_temp_c_x100": 32768},
        {"uptime_seconds": 2**32},
        {"load_left_raw": -(2**31) - 1},
    ],
)
def test_encode_overflow_raises(kwargs):
    with pytest.raises(ValueError):
        reg.encode_snapshot(reg.Snapshot(**kwargs))


@pytest.mark.parametrize("n", [0, 39, 41])
def test_decode_wrong_length_raises(n):
    with pytest.raises(ValueError):
        reg.decode_snapshot([0] * n)


def test_decode_rejects_non_u16_word():
    with pytest.raises(ValueError):
        reg.decode_snapshot([0] * 39 + [70000])


def test_reserved_words_ignored_on_decode_and_zero_on_encode():
    words = [0] * reg.INPUT_COUNT
    words[reg.ADDR_RESERVED_139 - reg.INPUT_START] = 0xBEEF
    s = reg.decode_snapshot(words)
    assert reg.encode_snapshot(s)[reg.ADDR_RESERVED_139 - reg.INPUT_START] == 0
    assert not any(f.name.startswith("reserved") for f in dataclasses.fields(s))


def test_scaled_properties():
    s = reg.Snapshot(
        feed_ec_us_cm_x10=4257,
        permeate_ec_us_cm_x100=1830,
        permeate_flow_gpm_x1000=350,
        permeate_temp_c_x100=-250,
    )
    assert s.feed_ec_us_cm == pytest.approx(425.7)
    assert s.permeate_ec_us_cm == pytest.approx(18.3)
    assert s.permeate_flow_gpm == pytest.approx(0.35)
    assert s.permeate_temp_c == pytest.approx(-2.5)


def test_snapshot_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        reg.Snapshot().module_status = 1  # type: ignore[misc]


GOOD = [1, 7, int(reg.RoState.PRODUCTION), int(reg.PumpCommanded.ON), 0, 0, 0, 0]


def test_status_round_trip_and_valid():
    reg.validate_status(GOOD)
    s = reg.decode_status(GOOD)
    assert s.ro_state == 4 and s.status_sequence == 7
    assert reg.encode_status(s) == GOOD


def test_status_accepts_unknown_fault_code():
    reg.validate_status([1, 0, 6, 0, 9999, 3, 1, 0])


@pytest.mark.parametrize(
    "words",
    [
        GOOD[:7],  # short
        GOOD + [0],  # long
        [2] + GOOD[1:],  # schema major
        [1, 0, 8, 0, 0, 0, 0, 0],  # ro_state out of enum
        [1, 0, 1, 3, 0, 0, 0, 0],  # pump_commanded out of enum
        [1, 0, 6, 0, 1001, 4, 1, 0],  # severity out of enum
        [1, 0, 1, 0, 0, 0, 0, 1],  # reserved flag bit set
        [1, 0, 6, 0, 1001, 0, 1, 0],  # code set, severity none
        [1, 0, 6, 0, 0, 3, 1, 0],  # severity set, code zero
        [1, 0, 6, 0, 1001, 3, 0, 0],  # code set, count zero
        [1, 0, 1, 0, 0, 0, 2, 0],  # count set, no fault
        [1, 70000, 1, 0, 0, 0, 0, 0],  # word out of u16
    ],
)
def test_status_rejects(words):
    with pytest.raises(reg.StatusValidationError):
        reg.validate_status(words)


def test_controller_status_has_no_defaults():
    with pytest.raises(TypeError):
        reg.ControllerStatus()  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        reg.ControllerStatus(  # type: ignore[call-arg]
            status_schema_major=1,
            status_sequence=0,
            ro_state=1,
            controller_fault_code=0,
            controller_fault_severity=0,
            controller_fault_count=0,
            controller_flags=0,
        )


def test_controller_status_is_keyword_only():
    with pytest.raises(TypeError):
        reg.ControllerStatus(1, 0, 1, 0, 0, 0, 0, 0)  # type: ignore[misc]


def test_status_requires_sequence_progress_constant():
    assert reg.STATUS_REQUIRE_SEQUENCE_PROGRESS is True


def test_empty_flag_table_can_represent_zero():
    assert int(reg.ControllerFlags(0)) == 0
    assert reg.ControllerFlags.NONE == 0
