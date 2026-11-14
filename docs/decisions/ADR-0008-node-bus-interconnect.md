# ADR-0008: Multi-node bus and RJ45 24 V interconnect

**Status:** Proposed (2026-11-13) — pending owner review. Design basis: `docs/superpowers/specs/2026-11-13-sensor-node-interconnect-design.md`.

**Decision:** Replace the single sensor node with a bus of identical-hardware carrier boards (RO skid = unit 1, tank = unit 2) polled by the main controller over RS485 Modbus RTU. A shielded Cat5e/Cat6 trunk with RJ45 connectors joins them in a daisy chain, carrying 24 V, GND and RS485 (pinout: `hardware/interconnect/pinout.yaml`). RS485 on the nodes is non-isolated because the trunk carries a common GND; an isolated-transceiver footprint is kept as an option.

**Rationale:**
- Identical boards (node type chosen by firmware profile and the DIP-switch ID) reduce hardware variants and allow adding nodes without redesign.
- One 24 V supply on the trunk removes a separate power run to each node.
- RJ45 was chosen by the owner over M12 despite the risk of confusion with Ethernet. The risk is mitigated by color (red cable and jacks), a "RO BUS - 24V" label on every port, and policy: never terminate in a switch or patch panel, never plug into the controller's Ethernet port.
- Non-isolated RS485 is acceptable only because power and ground already share the trunk; the ground scheme is unverified.

**Consequences:**
- Protocol 1.2 adds `node_type` and `installed_mask`; existing addresses are unchanged (AGENTS.md rule 2).
- The controller holds a node list with criticality; a missing or stale critical node inhibits RO production.
- Ethernet-confusion risk remains a human-factors risk, not eliminated.
- Hardware docs updated: `hardware/interconnect/NODE_BUS_INTERCONNECT.md`, sensor-node `HARDWARE_SPEC.md`, `POWER_AND_WIRING.md`, controller `WIRING.md`.

**TBD (do not guess):** termination and bias resistor values; transceiver part; maximum trunk length, voltage drop and per-node current (current under 200 mA is an assumption); whether to use the isolated footprint (verify the ground scheme in Stage D); pressure transducer model and ADC input protection; supply choice for valves and contactor coil.
