# Multi-node sensor system and standard interconnect — design

Date: 2026-11-13. Status: draft for review.

## 1. Scope
Replace the single-sensor-node assumption with a bus of identical-hardware sensor nodes polled by the main controller over RS485 Modbus RTU. Two nodes to start; more can be added without hardware or firmware redesign.

| Node | Unit ID | Type | Sensors |
|---|---|---|---|
| RO skid | 1 | `node_type` 0 | feed EC, permeate EC, 2 flow meters (pulse), 2 thermistors, optional pressure |
| Tank | 2 | `node_type` 1 | 2 HX711 load cells (tank volume), optional pressure |

The main controller (Waveshare ESP32-S3-ETH-8DI-8RO) is the RS485 master. No node can command an actuator (unchanged).

## 2. Standard interconnect (trunk)
Shielded Cat5e/Cat6, T568B wiring, RJ45 shell bonded to shield. Daisy-chain controller → node 1 → node 2 → ... Every node has two parallel RJ45 jacks (IN/OUT).

| Pin | Signal |
|---|---|
| 1, 2 | +24 V (two conductors in parallel) |
| 3, 6 | Reserved, unconnected |
| 4, 5 | RS485 A, B (twisted pair) |
| 7, 8 | GND (two conductors in parallel) |
| Shell | Shield |

- Power: one 24 V supply (also feeds the controller, which accepts 7–36 V). Node current assumed under 200 mA; voltage drop and maximum trunk length are TBD (measure in Stage D).
- Termination: switchable 120 ohm at the two end nodes only. Bias at the controller only.
- Shield bonded to chassis at the controller end only.
- **Ethernet hazard:** the controller has a genuine Ethernet RJ45. Use distinctly colored (red) cable and jacks, label every port "RO BUS – 24V", and never terminate this cable in a switch or patch panel.

## 3. Node hardware (one carrier board for all node types)
- Input: fuse, reverse-polarity protection, TVS; 24 V buck to 5 V; 3.3 V regulation.
- RS485: 3.3 V transceiver, non-isolated (the trunk carries common GND). Isolated-transceiver footprint kept as an option; ground scheme verified in Stage D.
- Node ID: 4-position DIP switch, read at boot (IDs 1–15). Duplicate or out-of-range ID: node stays silent.
- USB programming port, status LED, hardware watchdog.
- **Optional pressure channel (every node):** one input with 5 V transducer excitation, protection network, and a spare ADS1115 channel. A solder jumper selects 0.5–4.5 V ratiometric or 4–20 mA (250 ohm sense resistor, loop power from 24 V). Monitoring only; the independent hardwired pressure cutoff remains mandatory.
- RO-skid node front end: two ADS1115 (EC + pressure on one, thermistors on the other); two level-conditioned pulse inputs on ESP32 PCNT.
- Tank node front end: two HX711, 5 V load-cell excitation, one ADS1115 for pressure.

## 4. Protocol
- Shared 40-word register layout for all node types (protocol 1.2). Register 133 `node_type` (u16, enum: 0 `ro_skid`, 1 `tank`) and register 134 `installed_mask` (u16, same bit assignments as `validity_mask`; a set bit means that sensor is physically fitted).
- Invariant: `validity_mask & ~installed_mask == 0`. A fitted but failing sensor has its installed bit set and its validity bit clear; a sensor not fitted has neither. The existing `ro_feed_pressure_psi_x10` (address 115, validity bit 6) is the optional pressure channel on every node type. Existing offsets 100-132 are unchanged (AGENTS.md rule 2); protocol version 1.1 to 1.2.
- Optional pressure channel: not installed means the installed bit is clear, which is not a fault. Installed but implausible or lost clears the validity bit and raises a fault.
- Controller holds a configured node list (ID, type, criticality). A missing or stale critical node inhibits RO production; a missing non-critical node logs a fault. Stale data, implausible readings and inconsistent snapshots are invalid (AGENTS.md rule 4).

## 5. Firmware
Arduino-ESP32 C++ with PlatformIO (ADR-0007). One codebase, build profile per node type. Drivers (ADS1115, PCNT flow, HX711) behind interfaces with mocks. One coherent snapshot per cycle with sequence number and age. No sensor value is ever substituted by a plausible default.

## 6. Testing
Extend the Stage A host simulator to run N simulated nodes on one bus. Cases: duplicate ID, node dropout mid-poll, stale snapshot, corrupt frame, uninstalled vs. failed pressure channel, address-base, signed and 32-bit word-order checks.

## 7. Open TBDs (not guessed)
- ESP32-S3 dev board model and all GPIO assignments.
- Flow meter model: pulse voltage/type, K-factor, thermistor type and bias resistor.
- EC module model: output range, ADS1115 input scaling.
- Pressure transducer model and range; ADC protection values.
- Maximum trunk length and per-node current (measure in Stage D).
