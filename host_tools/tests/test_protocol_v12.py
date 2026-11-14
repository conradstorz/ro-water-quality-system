"""Protocol 1.2 guards: v1.1 addresses frozen; identity registers (window/minor now 1.3)."""

from ro_tools import schema
from ro_tools.generated import registers as reg

# Frozen v1.1 contract: name -> (address, type, scale_divisor). Never edit these rows.
V11_INPUT: dict[str, tuple[int, str, int]] = {
    "protocol_major": (100, "u16", 1),
    "protocol_minor": (101, "u16", 1),
    "snapshot_sequence": (102, "u16", 1),
    "module_status": (103, "u16", 1),
    "validity_mask": (104, "u16", 1),
    "fault_mask": (105, "u16", 1),
    "critical_age_ms": (106, "u16", 1),
    "uptime_seconds": (107, "u32", 1),
    "feed_ec_us_cm_x10": (109, "u16", 10),
    "permeate_ec_us_cm_x100": (110, "u16", 100),
    "permeate_flow_gpm_x1000": (111, "u16", 1000),
    "concentrate_flow_gpm_x1000": (112, "u16", 1000),
    "permeate_temp_c_x100": (113, "i16", 100),
    "concentrate_temp_c_x100": (114, "i16", 100),
    "ro_feed_pressure_psi_x10": (115, "u16", 10),
    "tank_volume_gal_x100": (116, "u16", 100),
    "load_left_raw": (117, "i32", 1),
    "load_right_raw": (119, "i32", 1),
    "permeate_total_pulses": (121, "u32", 1),
    "concentrate_total_pulses": (123, "u32", 1),
    "boot_counter": (125, "u32", 1),
    "sample_interval_ms": (127, "u16", 1),
    "sensor_error_code": (128, "u16", 1),
    "feed_ec_raw_adc": (129, "u16", 1),
    "permeate_ec_raw_adc": (130, "u16", 1),
    "pressure_raw_adc": (131, "u16", 1),
    "feed_temp_c_x100": (132, "i16", 100),
}


def test_v11_input_registers_unchanged():
    by_name = {r.name: r for r in schema.load().input_registers}
    for name, (addr, typ, div) in V11_INPUT.items():
        r = by_name[name]
        assert (r.address, r.type, r.scale_divisor, r.access) == (addr, typ, div, "read_only"), name


def test_polling_window_is_v13():
    m = schema.load()
    assert (m.input_start, m.input_count) == (100, 100)


def test_node_identity_registers():
    m = schema.load()
    by_name = {r.name: r for r in m.input_registers}
    node_type = by_name["node_type"]
    assert (node_type.address, node_type.type, node_type.enum) == (133, "u16", "node_type")
    installed = by_name["installed_mask"]
    assert (installed.address, installed.type, installed.access) == (134, "u16", "read_only")
    assert m.enums["node_type"] == {0: "ro_skid", 1: "tank"}
    assert (m.version_major, m.version_minor) == (1, 3)


def test_generated_module_exposes_identity():
    assert reg.PROTOCOL_MINOR == 3
    assert reg.ADDR_NODE_TYPE == 133
    assert reg.ADDR_INSTALLED_MASK == 134
    assert int(reg.NodeType.RO_SKID) == 0
    assert int(reg.NodeType.TANK) == 1
    snap = reg.decode_snapshot([0] * reg.INPUT_COUNT)
    assert snap.node_type == 0
    assert snap.installed_mask == 0
