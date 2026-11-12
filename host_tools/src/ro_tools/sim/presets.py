"""Named scenario presets. All values are SIMULATED, not equipment limits."""

from __future__ import annotations

from ro_tools.generated.registers import FaultBits, StatusBits, ValidityBits
from ro_tools.sim.register_bank import RegisterBank
from ro_tools.sim.server import Responder

PRESETS: tuple[str, ...] = (
    "healthy",
    "critical_sensor_invalid",
    "stale",
    "frozen_sequence",
    "silent",
)

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


def _healthy(bank: RegisterBank) -> None:
    """Load the SIMULATED healthy snapshot into the pending buffer."""
    for name, raw in _HEALTHY_FIELDS.items():
        bank.set_field(name, raw)
    bank.set_status(StatusBits.OPERATIONAL)
    bank.set_validity(_HEALTHY_VALIDITY)
    bank.set_faults(0)


def apply_preset(responder: Responder, name: str) -> None:
    """Apply a named scenario to a responder and commit its bank.

    :param responder: Responder whose bank and drop flag are set.
    :param name: One of :data:`PRESETS`.
    :raises ValueError: If ``name`` is unknown (the bank is left untouched).
    """
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; choose from {PRESETS}")
    bank = responder.bank
    responder.drop_responses = False
    bank.freeze_sequence(False)
    _healthy(bank)
    if name == "critical_sensor_invalid":
        bank.set_validity(_HEALTHY_VALIDITY & ~int(ValidityBits.PERMEATE_EC))
        bank.set_faults(FaultBits.EC_PERMEATE_FAULT)
    elif name == "stale":
        bank.force_critical_age(65535)
        bank.set_faults(FaultBits.STALE_ACQUISITION)
    elif name == "frozen_sequence":
        bank.commit()
        bank.freeze_sequence(True)
    elif name == "silent":
        responder.drop_responses = True
    bank.commit()
