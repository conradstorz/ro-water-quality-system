"""Named scenario presets. All values are SIMULATED, not equipment limits."""

from __future__ import annotations

from dataclasses import dataclass

from ro_tools.generated.registers import FaultBits, NodeType, StatusBits, ValidityBits
from ro_tools.onewire import (
    FAMILY_DS18B20,
    FAMILY_DS2438,
    NO_BUS_STATUS,
    BusStatus,
    OneWireDevice,
    make_rom,
)
from ro_tools.sim.register_bank import ALL_SENSORS, RegisterBank
from ro_tools.sim.server import Responder

PRESETS: tuple[str, ...] = (
    "healthy",
    "critical_sensor_invalid",
    "stale",
    "frozen_sequence",
    "silent",
    "pressure_failed",
    "onewire_healthy",
    "onewire_lost",
    "onewire_crc_error",
    "onewire_overflow",
)

# SIMULATED 1-Wire devices; serials and readings are illustrative only.
_OW_DS18B20_ROM = make_rom(FAMILY_DS18B20, 0x000000000001)
_OW_DS2438_ROM = make_rom(FAMILY_DS2438, 0x000000000002)


def _ow_devices(
    *, lost: bool = False, crc_error: bool = False
) -> tuple[OneWireDevice, OneWireDevice]:
    """Build the SIMULATED DS18B20 + DS2438 pair, optionally degrading the DS18B20.

    :param lost: Mark the DS18B20 as missing.
    :param crc_error: Mark the DS18B20 as having a CRC error.
    :returns: The two devices.
    """
    if lost:
        temp = OneWireDevice(_OW_DS18B20_ROM, present=False, valid=False, missing=True)
    elif crc_error:
        temp = OneWireDevice(_OW_DS18B20_ROM, valid=False, crc_error=True)
    else:
        temp = OneWireDevice(_OW_DS18B20_ROM, primary=2150)
    return temp, OneWireDevice(_OW_DS2438_ROM, primary=2210, secondary=3300)


# SIMULATED illustrative values from protocol/examples/sample_snapshot.json.
_HEALTHY_FIELDS: dict[str, int] = {
    "feed_ec_us_cm_x10": 4257,
    "permeate_ec_us_cm_x100": 1830,
    "permeate_flow_gpm_x1000": 350,
    "concentrate_flow_gpm_x1000": 1050,
    "ro_feed_pressure_psi_x10": 1250,
    "tank_volume_gal_x100": 2870,
    "permeate_temp_c_x100": 1500,
    "concentrate_temp_c_x100": 1500,
    "critical_age_ms": 100,
}


_HEALTHY_VALIDITY: int = sum(
    int(bit) for bit in ValidityBits if bit != ValidityBits.FEED_TEMP_OPTIONAL
)

_V = ValidityBits
_RO_BITS: int = int(
    _V.FEED_EC
    | _V.PERMEATE_EC
    | _V.PERMEATE_FLOW
    | _V.CONCENTRATE_FLOW
    | _V.PERMEATE_TEMP
    | _V.CONCENTRATE_TEMP
    | _V.RO_FEED_PRESSURE
)
_TANK_BITS: int = int(_V.TANK_VOLUME | _V.LEFT_LOAD_CELL | _V.RIGHT_LOAD_CELL)


@dataclass(frozen=True)
class NodeProfile:
    """What one simulated node physically has and what a healthy reading looks like.

    :ivar name: Profile name, for messages.
    :ivar node_type: ``node_type`` register value.
    :ivar installed: ``installed_mask`` register value.
    :ivar validity: Validity bits set in the healthy state (subset of ``installed``).
    :ivar fields: SIMULATED healthy raw register values.
    :ivar victim: Validity bit cleared by ``critical_sensor_invalid``.
    :ivar victim_fault: Fault bit raised together with it.
    """

    name: str
    node_type: int
    installed: int
    validity: int
    fields: dict[str, int]
    victim: ValidityBits
    victim_fault: FaultBits


FULL_PROFILE = NodeProfile(
    name="full",
    node_type=int(NodeType.RO_SKID),
    installed=ALL_SENSORS,
    validity=_HEALTHY_VALIDITY,
    fields=dict(_HEALTHY_FIELDS),
    victim=ValidityBits.PERMEATE_EC,
    victim_fault=FaultBits.EC_PERMEATE_FAULT,
)

RO_SKID_PROFILE = NodeProfile(
    name="ro_skid",
    node_type=int(NodeType.RO_SKID),
    installed=_RO_BITS,
    validity=_RO_BITS,
    fields={
        "feed_ec_us_cm_x10": 4257,
        "permeate_ec_us_cm_x100": 1830,
        "permeate_flow_gpm_x1000": 350,
        "concentrate_flow_gpm_x1000": 1050,
        "ro_feed_pressure_psi_x10": 1250,
        "permeate_temp_c_x100": 1500,
        "concentrate_temp_c_x100": 1500,
        "critical_age_ms": 100,
    },
    victim=ValidityBits.PERMEATE_EC,
    victim_fault=FaultBits.EC_PERMEATE_FAULT,
)

TANK_PROFILE = NodeProfile(
    name="tank",
    node_type=int(NodeType.TANK),
    installed=_TANK_BITS,
    validity=_TANK_BITS,
    fields={
        "tank_volume_gal_x100": 2870,
        "load_left_raw": 123456,
        "load_right_raw": 123400,
        "critical_age_ms": 100,
    },
    victim=ValidityBits.TANK_VOLUME,
    victim_fault=FaultBits.HX711_LEFT_FAULT,
)


def _healthy(bank: RegisterBank, profile: NodeProfile) -> None:
    """Load the SIMULATED healthy snapshot for ``profile`` into the pending buffer.

    :param bank: Bank to load.
    :param profile: Node profile.
    """
    bank.configure_node(profile.node_type, profile.installed)
    for name, raw in profile.fields.items():
        bank.set_field(name, raw)
    bank.set_status(StatusBits.OPERATIONAL)
    bank.set_validity(profile.validity)
    bank.set_faults(0)
    bank.set_onewire((), NO_BUS_STATUS)


def apply_preset(responder: Responder, name: str, profile: NodeProfile = FULL_PROFILE) -> None:
    """Apply a named scenario to a responder and commit its bank.

    :param responder: Responder whose bank and drop flag are set.
    :param name: One of :data:`PRESETS`.
    :param profile: Which node is being simulated; defaults to the legacy full node.
    :raises ValueError: If ``name`` is unknown, or ``pressure_failed`` is requested for a
        profile with no pressure channel (the bank is left untouched).
    """
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {PRESETS}")
    if name == "pressure_failed" and not profile.installed & int(ValidityBits.RO_FEED_PRESSURE):
        raise ValueError(f"profile {profile.name!r} has no pressure channel")
    bank = responder.bank
    responder.drop_responses = False
    bank.freeze_sequence(False)
    _healthy(bank, profile)
    if name == "critical_sensor_invalid":
        bank.set_validity(profile.validity & ~int(profile.victim))
        bank.set_faults(profile.victim_fault)
    elif name == "stale":
        bank.force_critical_age(65535)
        bank.set_faults(FaultBits.STALE_ACQUISITION)
    elif name == "frozen_sequence":
        bank.commit()
        bank.freeze_sequence(True)
    elif name == "silent":
        responder.drop_responses = True
    elif name == "pressure_failed":
        bank.set_validity(profile.validity & ~int(ValidityBits.RO_FEED_PRESSURE))
        bank.set_faults(FaultBits.PRESSURE_FAULT)
    elif name == "onewire_healthy":
        bank.set_onewire(_ow_devices())
    elif name == "onewire_lost":
        bank.set_onewire(_ow_devices(lost=True))
        bank.set_faults(FaultBits.ONEWIRE_BUS_FAULT)
    elif name == "onewire_crc_error":
        bank.set_onewire(_ow_devices(crc_error=True), BusStatus.CRC_ERRORS)
        bank.set_faults(FaultBits.ONEWIRE_BUS_FAULT)
    elif name == "onewire_overflow":
        devices = [OneWireDevice(make_rom(FAMILY_DS18B20, n), primary=2150) for n in range(1, 10)]
        bank.set_onewire(devices, BusStatus.OVERFLOW)
        bank.set_faults(FaultBits.ONEWIRE_BUS_FAULT)
    bank.commit()
