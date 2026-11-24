# Power and wiring plan
- 120VAC: RO booster pump through motor-rated contactor + protective interlocks; distribution pump independently through pressure switch and dry-run protection.
- 12VDC: valve actuators and the contactor coil if selected compatible; final voltage and supply TBD (the main controller is on the 24 V supply below, not this rail). Each branch fused and sized for inrush.
- 24VDC node bus: one supply feeds the controller and all sensor nodes through the RJ45 trunk (see hardware/interconnect/NODE_BUS_INTERCONNECT.md); fuse per node. The controller accepts 7-36 V and runs from this same 24 V supply; the supply choice for valves and the contactor coil remains TBD.
- 5VDC: sensor board/sensor electronics is derived on each node from the 24 V trunk by a TI LMR36015 buck (4.2-60 V in, 1.5 A), behind a Bourns MF-R065 PTC, an MBRS3100 reverse-polarity Schottky and an SMBJ33A TVS. 3.3 V logic comes from the DevKitC's SGM2212-3.3 (800 mA). Per-node budget: 279.1 mA from 24 V (ADR-0012, section 2.1; hardware/sensor-node/HARDWARE_SPEC.md).
- Solenoid/actuator coil suppression appropriate to AC/DC type and manufacturer instructions; do not assume a two-wire auto-return ball valve behaves like a simple DC solenoid.
- Keep mains and low-voltage separated; confirm protective earth and isolation boundaries.
