# Safety requirements (mandatory)
- RO pump is 120 VAC and must use a **motor-rated** contactor/overload protection, not a generic 10 A PCB relay as a motor starter.
- Independent hardwired high-pressure cutoff and high-high tank-level cutoff interrupt pump enable; a correctly sized mechanical relief protects the pump discharge, including blockage at the post-pump filter.
- Low feed pressure / dry-run protection is independent where required by pump design. Determine safe startup behavior after pump identification.
- Distribution pump is separate 120 VAC equipment controlled by its own pressure switch; independent low-water protection is required. Sensor ESP32 does not actuate it.
- RO flush valve USS-MSV00072 is **provisional**: advertised 145 PSI maximum vs remembered ~125 PSI operating pressure. Do not install until pressure suitability and maximum transient/relief conditions are resolved.
- On ESP32 reset or comms failure: RO contactor deenergized, flush valve unpowered/open, permeate diverted to drain (subject to verified valve hardware).
- Software must not override physical interlocks. Modbus is not a safety-rated bus.
- All wetted and electrical parts must be rated for measured conditions; sanitary atmospheric tank, filtered vent, overflow air gap, potable water materials, maintenance/sanitation.
- Use qualified electrical practices for mains wiring, grounding, fusing, separation, and enclosure construction.
