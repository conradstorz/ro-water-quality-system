# RO node bus interconnect (RJ45 trunk)

Design basis: `docs/superpowers/specs/2026-11-13-sensor-node-interconnect-design.md`, section 2. Decision record: `docs/decisions/ADR-0008-node-bus-interconnect.md`. The normative pinout is `hardware/interconnect/pinout.yaml`; the table below must match it (checked by `host_tools/tests/test_interconnect_docs.py`).

## Purpose
One standard cable joins the main controller and every sensor node. It carries 24 V power, ground and the RS485 Modbus RTU bus (controller = master, nodes = servers). Nodes are identical carrier boards (RO skid = unit 1, tank = unit 2); more can be added by plugging in another node. No node can command an actuator.

## Cable
Shielded Cat5e or Cat6, T568B wiring, **red** cable and red jacks. Shielded RJ45 connectors with the shell bonded to the cable shield.

## Pinout

| Pin | Signal |
|---|---|
| 1, 2 | +24V |
| 3, 6 | Reserved |
| 4 | RS485 A |
| 5 | RS485 B |
| 7, 8 | GND |
| Shell | Shield |

- Pins 1 and 2 (+24 V) and pins 7 and 8 (GND) are two conductors in parallel each.
- Pins 3 and 6 are reserved and unconnected. Do not use them.
- RS485 A/B is the center twisted pair (pins 4 and 5) and is not adjacent to a power pin. Which of A/B matches the controller vendor's D+/D- labels is unverified; confirm on the bench (see `hardware/main-controller/WIRING.md` section 3).

## Topology
Daisy chain: controller -> node 1 -> node 2 -> ... Every node has two RJ45 jacks, IN and OUT, wired in parallel on the board. Stubs must be short (only the on-board trace to the transceiver). No star or tee wiring.

## Termination and bias
- Termination: switchable 120 ohm at the two end devices of the chain only. Any other device leaves it off.
- Bias: at the controller only (one point). Bias resistor values are TBD pending the transceiver choice and a bench check of the idle bus.
- The controller has its own 120 ohm jumper cap (`hardware/main-controller/WIRING.md`); account for it when deciding which devices terminate. TBD.

## Shield
Shell and shield wire bonded to chassis at the controller end only. At nodes the shield is carried through IN to OUT but not bonded to the node ground.

## Power
- One 24 V supply feeds the controller (accepts 7-36 V) and all nodes through the trunk. Fuse per node.
- Per-node current under 200 mA is an **ASSUMPTION**, not a measurement.
- Maximum trunk length and voltage drop are TBD. Measure in Stage D; do not rely on any figure before then.

## Ethernet hazard
This is a plain RJ45 and the controller has a genuine Ethernet RJ45. Plugging 24 V into Ethernet equipment can damage it. Mitigations (the owner chose RJ45 over M12, ADR-0008):
- Distinct color: red cable and red jacks. Reserve red cable and jacks for this bus only.
- Label every port and cable end "RO BUS - 24V".
- Never terminate this cable in a switch or patch panel.
- Never plug it into the controller's Ethernet port.

## Node ID
4-position DIP switch read at boot, IDs 1-15. A duplicate or out-of-range ID leaves the node silent (it does not answer on the bus).

## 1-Wire bus
Design basis: `docs/superpowers/specs/2026-11-13-onewire-input-design.md`. Decision record: `docs/decisions/ADR-0009-onewire-monitoring-input.md`. Normative data: the `onewire` section of `hardware/interconnect/pinout.yaml`. **Monitoring only**: 1-Wire data never permits or inhibits RO production.

This connector is not for the RJ45 RO BUS. It is a separate, local sensor bus on each node.

- Connector: Nilight 3-pin waterproof male/female harness connector. Inline wire-to-wire, not panel mount.
- Each node has a short pigtail through a cable gland, one male-end and one female-end, so the chain runs in one direction. Daisy-chain at plug/socket pairs.
- Signals: +5V, DATA, GND. Cavity numbering is TBD until confirmed against the actual part.
- Label every plug "1-WIRE".
- Keep 1-WIRE wiring away from the 24 V trunk and RS485 wiring.
- Hazard: generic 3-pin automotive plugs mate with each other. Only the label and routing prevent a wrong mating.
- Power: node 5 V rail, non-parasitic, through a polyfuse (rating TBD).
- Shield, if used, is bonded at the node end only.
- rating_voltage: TBD
- rating_current: TBD
- Pull-up value, GPIO, maximum cable length and device count: TBD (measure in Stage D).

## Open TBDs
- Termination and bias resistor values; transceiver part.
- Maximum trunk length, voltage drop and per-node current (measure in Stage D).
- Isolated versus non-isolated transceiver, ground scheme (verify in Stage D).
- Controller RS485 A/B polarity versus the vendor labels; whether the controller biases the bus.
- Whether the controller's built-in 120 ohm termination is at a chain end.
- ESP32-S3 board model and GPIO assignments (not defined here).
- 1-Wire (all TBD): connector cavity numbering, connector voltage/current rating, polyfuse rating, pull-up value, GPIO, maximum cable length and device count.
