# Power and wiring plan
- 120VAC: RO booster pump through motor-rated contactor + protective interlocks; distribution pump independently through pressure switch and dry-run protection.
- 12VDC: valve actuators and the contactor coil if selected compatible; final voltage and supply TBD (the main controller is on the 24 V supply below, not this rail). Each branch fused and sized for inrush.
- 24VDC node bus: one supply feeds the controller and all sensor nodes through the RJ45 trunk (see hardware/interconnect/NODE_BUS_INTERCONNECT.md); fuse per node. The controller accepts 7-36 V and runs from this same 24 V supply; the supply choice for valves and the contactor coil remains TBD.
- 5VDC: sensor board/sensor electronics through regulated 12-to-5V converter; 3.3V logic as needed.
- Solenoid/actuator coil suppression appropriate to AC/DC type and manufacturer instructions; do not assume a two-wire auto-return ball valve behaves like a simple DC solenoid.
- Keep mains and low-voltage separated; confirm protective earth and isolation boundaries.
