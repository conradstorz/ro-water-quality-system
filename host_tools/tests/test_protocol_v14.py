"""Protocol 1.4 guards: 1-Wire name table 240-322 is additive; v1.3 registers frozen."""

from ro_tools import schema
from ro_tools.generated import registers as reg

# Frozen v1.3 contract subset: address -> (name, type, scale_divisor, access).
V13_REGISTERS: dict[int, tuple[str, str, int, str]] = {
    100: ("protocol_major", "u16", 1, "read_only"),
    115: ("ro_feed_pressure_psi_x10", "u16", 10, "read_only"),
    131: ("pressure_raw_adc", "u16", 1, "read_only"),
    133: ("node_type", "u16", 1, "read_only"),
    134: ("installed_mask", "u16", 1, "read_only"),
    140: ("onewire_device_count", "u16", 1, "read_only"),
    144: ("onewire_s0_rom0", "u16", 1, "read_only"),
    199: ("onewire_s7_status", "u16", 1, "read_only"),
    200: ("configuration_schema_version", "u16", 1, "read_only"),
    202: ("device_id", "u16", 1, "read_only"),
    220: ("status_schema_major", "u16", 1, "write_multiple_only"),
    227: ("controller_flags", "u16", 1, "write_multiple_only"),
}

ROM_WORDS = 4
LABEL_WORDS = 6
ENTRY_STRIDE = ROM_WORDS + LABEL_WORDS
ENTRY_MAX = 8


def _expected_name_table() -> dict[int, str]:
    out = {240: "names_schema_major", 241: "names_revision", 242: "names_entry_count"}
    for n in range(ENTRY_MAX):
        base = 243 + ENTRY_STRIDE * n
        for i in range(ROM_WORDS):
            out[base + i] = f"names_e{n}_rom{i}"
        for i in range(LABEL_WORDS):
            out[base + ROM_WORDS + i] = f"names_e{n}_label{i}"
    return out


def test_version_and_windows():
    m = schema.load()
    assert (m.version_major, m.version_minor) == (1, 4)
    assert reg.PROTOCOL_MINOR == 4
    assert (m.input_start, m.input_count) == (100, 100)
    assert (m.status_start, m.status_count) == (220, 8)
    assert (reg.STATUS_START, reg.STATUS_COUNT) == (220, 8)


def test_v13_registers_unchanged():
    m = schema.load()
    by_addr = {r.address: r for r in m.input_registers + m.holding_registers}
    for addr, (name, typ, div, access) in V13_REGISTERS.items():
        r = by_addr[addr]
        assert (r.name, r.type, r.scale_divisor, r.access) == (name, typ, div, access), addr


def test_name_table_exact_layout():
    m = schema.load()
    expected = _expected_name_table()
    assert len(expected) == 83
    assert min(expected) == 240 and max(expected) == 322
    table = {r.address: r for r in m.holding_registers if 240 <= r.address <= 322}
    assert {a: r.name for a, r in table.items()} == expected
    for r in table.values():
        assert (r.type, r.words, r.scale_divisor, r.access) == (
            "u16",
            1,
            1,
            "write_multiple_only",
        ), r.name
    assert table[240].equals == 1
    assert all(r.equals is None for a, r in table.items() if a != 240)


def test_name_table_section_modelled():
    m = schema.load()
    assert (m.names_start, m.names_count) == (240, 83)
    assert m.names_schema_major == 1
    assert m.names_entry_count_max == 8
    assert m.names_label_words == 6


def test_write_multiple_only_is_exactly_two_blocks():
    m = schema.load()
    writable = {r.address for r in m.holding_registers if r.access == "write_multiple_only"}
    assert writable == set(range(220, 228)) | set(range(240, 323))


def test_generated_constants():
    assert (reg.NAMES_START, reg.NAMES_COUNT) == (240, 83)
    assert reg.NAMES_SCHEMA_MAJOR == 1
    assert reg.NAMES_ENTRY_MAX == 8
    assert reg.NAMES_ENTRY_STRIDE == 10
    assert reg.NAMES_ROM_WORDS == 4
    assert reg.NAMES_LABEL_WORDS == 6
    assert reg.NAMES_ENTRY_BASE == 243
    assert reg.ADDR_NAMES_SCHEMA_MAJOR == 240
    assert reg.ADDR_NAMES_E7_LABEL5 == 322


def test_status_block_untouched_by_name_table():
    assert [n for n, _, _ in reg.STATUS_LAYOUT] == [
        "status_schema_major",
        "status_sequence",
        "ro_state",
        "pump_commanded",
        "controller_fault_code",
        "controller_fault_severity",
        "controller_fault_count",
        "controller_flags",
    ]
    assert len(reg.ControllerStatus.__dataclass_fields__) == 8
