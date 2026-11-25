"""Tests for the pure simulated register bank."""

import struct
import threading

import pytest

from ro_tools.generated import registers as reg
from ro_tools.onewire import FAMILY_DS18B20, FAMILY_DS2438, make_rom
from ro_tools.onewire_names import NameEntry, encode_name_table
from ro_tools.sim.register_bank import (
    EXC_ILLEGAL_ADDRESS,
    EXC_ILLEGAL_FUNCTION,
    EXC_ILLEGAL_VALUE,
    RegisterBank,
)


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def bank(clock) -> RegisterBank:
    return RegisterBank(clock=clock)


def read(fc: int, addr: int, count: int) -> bytes:
    return struct.pack(">BHH", fc, addr, count)


def write16(addr: int, values: list[int]) -> bytes:
    return struct.pack(">BHHB", 16, addr, len(values), 2 * len(values)) + struct.pack(
        f">{len(values)}H", *values
    )


def words_of(resp: bytes) -> list[int]:
    assert resp[0] < 0x80, f"exception response {resp.hex()}"
    assert resp[1] == len(resp) - 2
    return list(struct.unpack(f">{resp[1] // 2}H", resp[2:]))


def exc(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


GOOD = [1, 5, 4, 1, 0, 0, 0, 0]


def test_new_bank_publishes_nothing_valid(bank):
    s = bank.published()
    assert (s.protocol_major, s.protocol_minor) == (reg.PROTOCOL_MAJOR, reg.PROTOCOL_MINOR)
    assert s.validity_mask == 0 and s.module_status == 0 and s.snapshot_sequence == 0


def test_fc04_full_block_decodes(bank):
    bank.set_field("feed_ec_us_cm_x10", 4257)
    bank.commit()
    s = reg.decode_snapshot(words_of(bank.handle_pdu(read(4, 100, reg.INPUT_COUNT))))
    assert s.feed_ec_us_cm_x10 == 4257 and s.snapshot_sequence == 1


def test_fc04_v12_reader_40_words_at_100_still_succeeds(bank):
    bank.set_field("feed_ec_us_cm_x10", 4257)
    bank.commit()
    words = words_of(bank.handle_pdu(read(4, 100, 40)))
    assert len(words) == 40
    assert words == words_of(bank.handle_pdu(read(4, 100, reg.INPUT_COUNT)))[:40]


def test_fc04_subrange(bank):
    bank.set_field("module_status", 0x0001)
    bank.commit()
    assert words_of(bank.handle_pdu(read(4, 103, 1))) == [1]


@pytest.mark.parametrize(("addr", "count"), [(99, 1), (100, 101), (199, 2), (200, 1), (0, 1)])
def test_fc04_outside_block_is_illegal_address(bank, addr, count):
    assert bank.handle_pdu(read(4, addr, count)) == exc(4, EXC_ILLEGAL_ADDRESS)


def test_fc03_metadata(bank):
    assert words_of(bank.handle_pdu(read(3, 200, 3))) == [1, 0, 1]


def test_fc03_status_block_is_zero_before_first_write(bank):
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == [0] * 8
    assert bank.controller_status is None
    assert bank.last_valid_status_received_ms is None


@pytest.mark.parametrize(
    ("addr", "count"),
    [(199, 1), (200, 4), (203, 1), (219, 2), (220, 9), (228, 1), (202, 19), (100, 1)],
)
def test_fc03_outside_ranges_is_illegal_address(bank, addr, count):
    assert bank.handle_pdu(read(3, addr, count)) == exc(3, EXC_ILLEGAL_ADDRESS)


@pytest.mark.parametrize("count", [0, 126])
def test_read_bad_quantity_is_illegal_value(bank, count):
    assert bank.handle_pdu(read(4, 100, count)) == exc(4, EXC_ILLEGAL_VALUE)


def test_fc16_valid_write_accepted(bank, clock):
    clock.t = 123.456
    assert bank.handle_pdu(write16(220, GOOD)) == struct.pack(">BHH", 16, 220, 8)
    assert bank.controller_status == reg.decode_status(GOOD)
    assert bank.last_valid_status_received_ms == 123456
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == GOOD


def test_fc16_unknown_fault_code_accepted(bank):
    words = [1, 0, 6, 0, 9999, 3, 1, 0]
    assert bank.handle_pdu(write16(220, words))[0] == 16
    assert bank.controller_status.controller_fault_code == 9999


@pytest.mark.parametrize(
    ("addr", "values"),
    [
        (220, GOOD[:7]),
        (221, GOOD[:7]),
        (220, GOOD + [0]),
        (219, [0] + GOOD),
        (222, [4]),
        (200, [1]),
        (200, [1, 0, 1]),
        (202, [1] * 26),
        (100, [0] * 8),
    ],
)
def test_fc16_wrong_range_is_illegal_address_and_preserves_status(bank, clock, addr, values):
    bank.handle_pdu(write16(220, GOOD))
    before = (bank.controller_status, bank.last_valid_status_received_ms)
    clock.t += 1
    assert bank.handle_pdu(write16(addr, values)) == exc(16, EXC_ILLEGAL_ADDRESS)
    assert (bank.controller_status, bank.last_valid_status_received_ms) == before


@pytest.mark.parametrize(
    "values",
    [
        [2, 5, 4, 1, 0, 0, 0, 0],
        [1, 5, 8, 1, 0, 0, 0, 0],
        [1, 5, 4, 3, 0, 0, 0, 0],
        [1, 5, 6, 0, 1001, 4, 1, 0],
        [1, 5, 4, 1, 0, 0, 0, 1],
        [1, 5, 6, 0, 1001, 0, 1, 0],
    ],
)
def test_fc16_bad_value_is_illegal_value_and_preserves_status(bank, clock, values):
    bank.handle_pdu(write16(220, GOOD))
    before = (bank.controller_status, bank.last_valid_status_received_ms)
    clock.t += 1
    assert bank.handle_pdu(write16(220, values)) == exc(16, EXC_ILLEGAL_VALUE)
    assert (bank.controller_status, bank.last_valid_status_received_ms) == before


def test_fc16_malformed_byte_count_is_illegal_value(bank):
    pdu = struct.pack(">BHHB", 16, 220, 8, 15) + b"\x00" * 16
    assert bank.handle_pdu(pdu) == exc(16, EXC_ILLEGAL_VALUE)
    assert bank.handle_pdu(write16(220, GOOD)[:-1]) == exc(16, EXC_ILLEGAL_VALUE)


@pytest.mark.parametrize("fc", [1, 2, 5, 6, 15, 22, 23, 43, 0x7F])
def test_other_function_codes_are_illegal_function(bank, fc):
    assert bank.handle_pdu(bytes([fc, 0, 220, 0, 1])) == exc(fc, EXC_ILLEGAL_FUNCTION)


def test_truncated_read_request_is_illegal_value(bank):
    assert bank.handle_pdu(bytes([4, 0, 100])) == exc(4, EXC_ILLEGAL_VALUE)


def test_pending_not_visible_until_commit(bank):
    bank.commit()
    bank.set_field("feed_ec_us_cm_x10", 999)
    assert bank.published().feed_ec_us_cm_x10 == 0
    bank.commit()
    assert bank.published().feed_ec_us_cm_x10 == 999


def test_sequence_rolls_over(bank):
    bank.set_field("snapshot_sequence", 65535)
    bank.freeze_sequence(True)
    bank.commit()
    assert bank.published().snapshot_sequence == 65535
    bank.freeze_sequence(False)
    bank.commit()
    assert bank.published().snapshot_sequence == 0


def test_frozen_sequence_does_not_advance(bank):
    bank.commit()
    bank.freeze_sequence(True)
    bank.commit()
    bank.commit()
    assert bank.published().snapshot_sequence == 1


def test_uptime_follows_clock(bank, clock):
    clock.t += 42.9
    bank.commit()
    assert bank.published().uptime_seconds == 42


def test_force_critical_age_saturates(bank):
    bank.force_critical_age(70000)
    bank.commit()
    assert bank.published().critical_age_ms == 65535
    with pytest.raises(ValueError):
        bank.force_critical_age(-1)


def test_saturate_sets_max_and_flag(bank):
    bank.saturate("permeate_total_pulses")
    bank.commit()
    s = bank.published()
    assert s.permeate_total_pulses == 0xFFFFFFFF
    assert s.module_status & reg.StatusBits.OVERFLOW_OR_SATURATION


def test_set_field_rejects_unknown_and_out_of_range(bank):
    with pytest.raises(KeyError):
        bank.set_field("nope", 1)
    with pytest.raises(ValueError):
        bank.set_field("module_status", 70000)


def test_mask_setters(bank):
    bank.set_validity(0x008F)
    bank.set_faults(0x0100)
    bank.set_status(0x0001)
    bank.commit()
    s = bank.published()
    assert (s.validity_mask, s.fault_mask, s.module_status) == (0x008F, 0x0100, 0x0001)


def test_reboot_discontinuity(bank, clock):
    bank.set_field("feed_ec_us_cm_x10", 4257)
    bank.commit()
    bank.commit()
    bank.handle_pdu(write16(220, GOOD))
    clock.t += 500
    bank.reboot()
    s = bank.published()
    assert s.boot_counter == 1
    assert s.uptime_seconds == 0
    assert s.snapshot_sequence == 0
    assert s.module_status & reg.StatusBits.WATCHDOG_RESET_SEEN
    assert s.feed_ec_us_cm_x10 == 4257
    assert bank.controller_status is None
    assert bank.last_valid_status_received_ms is None
    assert words_of(bank.handle_pdu(read(3, 220, 8))) == [0] * 8


def test_reader_never_sees_mixed_snapshot(bank):
    stop = threading.Event()

    def writer() -> None:
        v = 0
        while not stop.is_set():
            v = (v + 1) % 1000
            for name in ("feed_ec_us_cm_x10", "permeate_ec_us_cm_x100", "ro_feed_pressure_psi_x10"):
                bank.set_field(name, v)
            bank.commit()

    t = threading.Thread(target=writer, daemon=True)
    t.start()
    try:
        for _ in range(3000):
            s = reg.decode_snapshot(words_of(bank.handle_pdu(read(4, 100, reg.INPUT_COUNT))))
            assert s.feed_ec_us_cm_x10 == s.permeate_ec_us_cm_x100 == s.ro_feed_pressure_psi_x10
    finally:
        stop.set()
        t.join()


def _good_with_sequence(seq: int) -> list[int]:
    return [1, seq, 4, 1, 0, 0, 0, 0]


def test_sequence_progress_is_none_before_any_write(bank):
    assert bank.last_status_sequence_progress_ms is None


def test_sequence_progress_set_on_first_valid_write(bank, clock):
    clock.t = 200.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    assert bank.last_status_sequence_progress_ms == 200000
    assert bank.last_valid_status_received_ms == 200000


def test_same_sequence_advances_received_but_not_progress(bank, clock):
    clock.t = 200.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    clock.t = 201.5
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    assert bank.last_valid_status_received_ms == 201500
    assert bank.last_status_sequence_progress_ms == 200000


def test_changed_sequence_advances_both(bank, clock):
    clock.t = 200.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    clock.t = 202.0
    bank.handle_pdu(write16(220, _good_with_sequence(6)))
    assert bank.last_valid_status_received_ms == 202000
    assert bank.last_status_sequence_progress_ms == 202000


def test_rejected_write_changes_neither_timestamp(bank, clock):
    clock.t = 200.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    clock.t = 205.0
    bad = _good_with_sequence(9)
    bad[2] = 99
    assert bank.handle_pdu(write16(220, bad)) == exc(16, EXC_ILLEGAL_VALUE)
    assert bank.last_valid_status_received_ms == 200000
    assert bank.last_status_sequence_progress_ms == 200000


def test_reboot_clears_sequence_progress_and_next_write_counts_as_progress(bank, clock):
    clock.t = 200.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    bank.reboot()
    assert bank.last_status_sequence_progress_ms is None
    clock.t = 210.0
    bank.handle_pdu(write16(220, _good_with_sequence(5)))
    assert bank.last_status_sequence_progress_ms == 210000


def test_last_rejection_none_initially(bank):
    assert bank.last_rejection is None


def test_last_rejection_names_bad_enum_on_fc16(bank):
    bad = list(GOOD)
    bad[2] = 99
    assert bank.handle_pdu(write16(220, bad)) == exc(16, EXC_ILLEGAL_VALUE)
    assert bank.last_rejection is not None
    assert "ro_state" in bank.last_rejection and "99" in bank.last_rejection


def test_last_rejection_after_out_of_range_read(bank):
    assert bank.handle_pdu(read(4, 100, 101)) == exc(4, EXC_ILLEGAL_ADDRESS)
    assert bank.last_rejection and "100" in bank.last_rejection


def test_last_rejection_for_unsupported_function(bank):
    bank.handle_pdu(bytes([6, 0, 0, 0, 1]))
    assert bank.last_rejection and "6" in bank.last_rejection


def test_last_rejection_cleared_by_good_request(bank):
    bank.handle_pdu(read(4, 100, 101))
    assert bank.last_rejection is not None
    bank.handle_pdu(read(4, 100, reg.INPUT_COUNT))
    assert bank.last_rejection is None


def test_reboot_at_max_boot_counter_saturates_and_flags(bank):
    bank.set_field("boot_counter", 0xFFFFFFFF)
    bank.reboot()
    s = reg.decode_snapshot(words_of(bank.handle_pdu(read(4, 100, reg.INPUT_COUNT))))
    assert s.boot_counter == 0xFFFFFFFF
    assert s.module_status & reg.StatusBits.OVERFLOW_OR_SATURATION
    assert s.module_status & reg.StatusBits.WATCHDOG_RESET_SEEN


def test_reboot_below_max_does_not_flag_overflow(bank):
    bank.reboot()
    assert not bank.published().module_status & reg.StatusBits.OVERFLOW_OR_SATURATION
    assert bank.published().boot_counter == 1


# --- Protocol 1.4 1-Wire name table (holding 240-322) ---------------------------------


NAMES = encode_name_table(
    [
        NameEntry(make_rom(FAMILY_DS2438, 2), "Tank air"),
        NameEntry(make_rom(FAMILY_DS18B20, 1), "Outside air"),
    ],
    revision=0x1234,
)
NAMES_2 = encode_name_table([NameEntry(make_rom(FAMILY_DS18B20, 3), "Feed")], revision=9)


def _bad_names(kind: str) -> list[int]:
    words = list(NAMES)
    if kind == "schema":
        words[0] = 2
    elif kind == "count":
        words[2] = 9
    elif kind == "unused_nonzero":
        words[reg.NAMES_ENTRY_BASE - reg.NAMES_START + 5 * reg.NAMES_ENTRY_STRIDE] = 1
    elif kind == "rom_crc":
        words[reg.NAMES_ENTRY_BASE - reg.NAMES_START] ^= 1
    elif kind == "empty_label":
        base = reg.NAMES_ENTRY_BASE - reg.NAMES_START + reg.NAMES_ROM_WORDS
        words[base : base + reg.NAMES_LABEL_WORDS] = [0] * reg.NAMES_LABEL_WORDS
    elif kind == "duplicate_rom":
        first = reg.NAMES_ENTRY_BASE - reg.NAMES_START
        second = first + reg.NAMES_ENTRY_STRIDE
        words[second : second + reg.NAMES_ROM_WORDS] = words[first : first + reg.NAMES_ROM_WORDS]
    return words


def test_name_table_is_zero_after_construction(bank):
    assert words_of(bank.handle_pdu(read(3, 240, 83))) == [0] * 83
    assert bank.name_table_words == (0,) * 83
    assert bank.names_supported


def test_name_table_write_accepted_and_read_back(bank):
    assert bank.handle_pdu(write16(240, NAMES)) == struct.pack(">BHH", 16, 240, 83)
    assert bank.last_rejection is None
    assert words_of(bank.handle_pdu(read(3, 240, 83))) == NAMES
    assert bank.name_table_words == tuple(NAMES)


@pytest.mark.parametrize(("addr", "count"), [(240, 1), (242, 5), (300, 23), (322, 1)])
def test_name_table_subrange_read_back(bank, addr, count):
    bank.handle_pdu(write16(240, NAMES))
    assert words_of(bank.handle_pdu(read(3, addr, count))) == NAMES[addr - 240 : addr - 240 + count]


@pytest.mark.parametrize(
    "kind", ["schema", "count", "unused_nonzero", "rom_crc", "empty_label", "duplicate_rom"]
)
def test_invalid_name_table_is_illegal_value_and_keeps_prior(bank, kind):
    bank.handle_pdu(write16(240, NAMES))
    assert bank.handle_pdu(write16(240, _bad_names(kind))) == exc(16, EXC_ILLEGAL_VALUE)
    assert bank.last_rejection is not None and "name table rejected" in bank.last_rejection
    assert words_of(bank.handle_pdu(read(3, 240, 83))) == NAMES


def test_valid_name_table_replaces_prior(bank):
    bank.handle_pdu(write16(240, NAMES))
    bank.handle_pdu(write16(240, NAMES_2))
    assert bank.name_table_words == tuple(NAMES_2)


@pytest.mark.parametrize(
    ("addr", "values"),
    [
        (240, NAMES[:82]),
        (241, NAMES[1:]),
        (241, NAMES[:82]),
        (239, [0] + NAMES[:82]),
        (240, NAMES + [0]),
        (250, [0] * 10),
        (322, [0]),
        (300, [0] * 40),
        (228, [0] * 20),
    ],
)
def test_partial_name_table_write_is_illegal_address_and_keeps_prior(bank, addr, values):
    bank.handle_pdu(write16(240, NAMES))
    assert bank.handle_pdu(write16(addr, values)) == exc(16, EXC_ILLEGAL_ADDRESS)
    assert bank.name_table_words == tuple(NAMES)


@pytest.mark.parametrize(("addr", "count"), [(239, 2), (322, 2), (323, 1), (230, 20), (240, 84)])
def test_fc03_straddling_name_table_is_illegal_address(bank, addr, count):
    assert bank.handle_pdu(read(3, addr, count)) == exc(3, EXC_ILLEGAL_ADDRESS)


def test_reboot_clears_name_table(bank):
    bank.handle_pdu(write16(240, NAMES))
    bank.reboot()
    assert words_of(bank.handle_pdu(read(3, 240, 83))) == [0] * 83


def test_commit_and_status_write_keep_name_table(bank):
    bank.handle_pdu(write16(240, NAMES))
    bank.set_validity(0)
    bank.commit()
    bank.handle_pdu(write16(220, GOOD))
    assert bank.name_table_words == tuple(NAMES)


def test_name_table_write_leaves_snapshot_and_status_mailbox_alone(bank, clock):
    bank.handle_pdu(write16(220, GOOD))
    before_words = bank.handle_pdu(read(4, 100, reg.INPUT_COUNT))
    before = (
        bank.published(),
        bank.controller_status,
        bank.last_valid_status_received_ms,
        bank.last_status_sequence_progress_ms,
    )
    clock.t += 5
    bank.handle_pdu(write16(240, NAMES))
    bank.handle_pdu(write16(240, _bad_names("schema")))
    assert bank.handle_pdu(read(4, 100, reg.INPUT_COUNT)) == before_words
    assert (
        bank.published(),
        bank.controller_status,
        bank.last_valid_status_received_ms,
        bank.last_status_sequence_progress_ms,
    ) == before


def test_load_name_table_validates_and_keeps_prior(bank):
    bank.load_name_table(NAMES)
    assert bank.name_table_words == tuple(NAMES)
    with pytest.raises(ValueError, match="rejected"):
        bank.load_name_table(_bad_names("count"))
    with pytest.raises(ValueError, match="83"):
        bank.load_name_table(NAMES[:82])
    assert bank.name_table_words == tuple(NAMES)


@pytest.fixture()
def legacy_bank(clock) -> RegisterBank:
    return RegisterBank(clock=clock, names_supported=False)


def test_legacy_bank_publishes_minor_3(legacy_bank):
    assert legacy_bank.published().protocol_minor == 3
    assert not legacy_bank.names_supported


@pytest.mark.parametrize(("addr", "count"), [(240, 83), (240, 1), (300, 5)])
def test_legacy_bank_fc03_names_is_illegal_address(legacy_bank, addr, count):
    assert legacy_bank.handle_pdu(read(3, addr, count)) == exc(3, EXC_ILLEGAL_ADDRESS)


def test_legacy_bank_fc16_names_is_illegal_address(legacy_bank):
    assert legacy_bank.handle_pdu(write16(240, NAMES)) == exc(16, EXC_ILLEGAL_ADDRESS)
    assert legacy_bank.last_rejection is not None
    assert "name table" not in legacy_bank.last_rejection
    assert legacy_bank.name_table_words == (0,) * 83


def test_legacy_bank_load_name_table_raises(legacy_bank):
    with pytest.raises(ValueError, match="1.3"):
        legacy_bank.load_name_table(NAMES)


def test_legacy_bank_still_serves_status_block(legacy_bank):
    assert legacy_bank.handle_pdu(write16(220, GOOD))[0] == 16
    assert words_of(legacy_bank.handle_pdu(read(3, 220, 8))) == GOOD


def test_no_critical_channel_installed_publishes_saturated_age(bank):
    bank.configure_node(int(reg.NodeType.RO_SKID), 0)
    bank.set_validity(0)
    bank.set_field("critical_age_ms", 0)
    bank.commit()
    assert bank.published().critical_age_ms == 65535
