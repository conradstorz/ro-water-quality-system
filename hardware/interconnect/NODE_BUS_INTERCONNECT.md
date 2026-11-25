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
Decided in ADR-0012, section 3.
- Termination: 120 ohm at the two end devices of the chain only. The controller is the head of the chain, so its own 120 ohm jumper cap (`hardware/main-controller/WIRING.md`) stays on. The far-end node fits its J_TERM jumper (120 ohm 1 %, 0.25 W). Every other node leaves it off.
- Node transceiver: TI THVD1450, 3.3 V, with open, short and idle-bus failsafe receivers. The nodes need no bias.
- Bias: only if the Stage D idle-bus check shows the controller's receiver needs it, and then at the controller only: 390 ohm pull-up on A and 390 ohm pull-down on B from 3.3 V (236 mV idle), or 680 ohm each from 5 V (211 mV). Fit nothing before that check.

## Shield
Shell and shield wire bonded to chassis at the controller end only. At nodes the shield is carried through IN to OUT but not bonded to the node ground.

## Power
- One 24 V supply feeds the controller (accepts 7-36 V) and all nodes through the trunk. Fuse per node.
- Per-node budget: 305.6 mA from 24 V, with every front end populated and owner parts carried as stated allowances (ADR-0012, section 2.2). This is a computed budget, not a measurement; confirm it in Stage D.
- Node fuse: Bourns MF-R065 resettable PTC, 0.47 A hold at 50 °C (ADR-0012). Input: MBRS3100 reverse-polarity Schottky, SMBJ33A TVS, LMR36015 buck to 5.31 V nominal; 3.3 V comes from the 1117 LDO on the node's ESP32-S3 board, fed directly through its 5Vin pin.
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
- Power: node 5 V rail, non-parasitic, through a Bourns MF-R010 polyfuse (0.10 A hold at 23 °C, ADR-0012).
- Shield, if used, is continuous along the chain and bonded at one point only; the bonding location is TBD.
- ROM notation: the `ro-tools` CLI prints a ROM as 16 hex digits in wire order, family byte first and CRC byte last (`format_rom` in `host_tools/src/ro_tools/onewire.py`). Controller bindings use that same text.
- rating_voltage: TBD
- rating_current: TBD
- Bus master: DS2482S-100+ I2C 1-Wire master at 0x18, so no GPIO is used; internal pull-up (RWPU 1000-1675 ohm) with active pullup; 33 ohm series resistor; TPD1E10B06 ESD on DATA and +5V (ADR-0012).
- Maximum cable length and device count: TBD (measure in Stage D).

## Open TBDs
- Whether the controller needs the bias above (Stage D idle-bus check).
- Maximum trunk length, voltage drop and measured per-node current (Stage D).
- Ground scheme with non-isolated node transceivers (verify in Stage D).
- Controller RS485 A/B polarity versus the vendor labels.
- 1-Wire: connector cavity numbering, connector voltage/current rating, maximum cable length and device count.

Closed by ADR-0012: transceiver part, termination plan (controller cap on, far-end node J_TERM), bias values, per-node current budget, board model and GPIO map (`hardware/sensor-node/pinout.yaml`), 1-Wire polyfuse, pull-up, series resistor and bus master.
