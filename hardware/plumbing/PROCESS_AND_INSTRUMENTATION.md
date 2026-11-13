# Hydraulic process and instrumentation baseline
Well -> two existing media pretreatment stages -> feed EC -> rotary-vane booster (assumed) -> mechanical relief -> post-pump particulate safety filter -> RO membrane 4x21 (model TBD).
Permeate -> gross permeate flow/temp -> permeate EC -> tee -> (tank branch, low-crack check valve TBD) -> atmospheric tank, piped to the tank top; highest line point about 5 ft above membrane. Tee drain branch -> normally closed solenoid (K3, energize to dump) -> air-gapped drain. Not fail-to-drain; see ADR-0006.
Concentrate -> parallel manual needle valve (normal minimum discharge path) and normally-open auto-return motorized flush valve -> recombine -> concentrate flow/temp -> air-gapped drain.
Atmospheric tank -> independent distribution pump + pressure switch + small bladder tank -> two ice makers + drinking faucet.
Tank weight: rear hinge, two front load cells; calibrate empirically. High-high level float independently disables booster.
All pressure ratings, flow ranges, potable-water compatibility, backflow protection, and actual relief discharge routing TBD pending component identification.
