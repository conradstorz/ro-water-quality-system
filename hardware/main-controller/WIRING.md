# Main controller wiring (draft, unverified)

Scope: Waveshare `ESP32-S3-ETH-8DI-8RO` main controller. Power input, RS485 to the sensor node, and relays K1 (pump contactor), K2 (concentrate bypass), K3 (permeate dump).

**Status: logical wiring only.** The vendor wiki publishes no terminal-block labels or schematic (`reference/README.md`). Every terminal name marked `[T]` below must be read from the board silkscreen and confirmed with a meter before connecting anything. Do not connect any load until project firmware has replaced the vendor firmware and relay boot state has been measured (reference/README.md "Safety-relevant findings" 1-4).

## 1. Overview

```
   24 VDC SUPPLY (one supply)            12 VDC RAIL (valves / contactor coil only;
   (fused per branch)                     final voltage and supply TBD)
          |                                        |
   +------+--------------+                 +-------+----------------+
   |                     |                 |                        |
F1 (board)        F4 (24 V trunk,     F2 (K2 / K3 valves)   F3 (K1 contactor
   |               fuse per node)             |              coil + safety loop)
   v                     |                    |                        |
+--------------------------------------+      |                        |
| MAIN CONTROLLER (ESP32-S3-ETH-8DI-8RO)|      |                        |
|                                      |      |                        |
|  PWR IN [T] 7-36 V +/- (24 V)        |      |                        |
|                                      |      |                        |
|  RS485 [T] A  B  GND ----> RJ45 trunk jack (A pin 4, B pin 5, GND 7/8)
|                                      |      |                        |
|  K1 [T] COM / NO  ------------------ +------+------> safety loop -> contactor coil
|  K2 [T] COM / NO or NC ------------- +--> concentrate bypass valve
|  K3 [T] COM / NO  ------------------ +--> permeate dump valve (NC type)
+--------------------------------------+

RJ45 trunk (24 V + GND + RS485, daisy chain): controller -> node 1 (RO skid) -> node 2 (tank) -> ...
Each sensor node takes 24 V from the trunk; it has its own regulation (sensor-node/HARDWARE_SPEC.md).
```

## 2. Power input

| From | To | Notes |
|---|---|---|
| 24 VDC supply (+) via F1 | Controller PWR IN (+) `[T]` | 7-36 V input; the controller runs from the same 24 V supply as the trunk (interconnect spec). Size F1 for the board, TBD. |
| 24 VDC supply (-) | Controller PWR IN (-) `[T]` | Common return with the trunk GND (pins 7/8). The 12 V valve/coil rail return relationship is TBD; keep all of it separate from mains earth. |
| 24 VDC via F4 | RJ45 trunk +24V (pins 1, 2) | F4 is the 24 V trunk fuse (fuse per node, values TBD). Sensor nodes take power from the trunk and have their own regulation (`sensor-node/HARDWARE_SPEC.md`). The 12 V rail (valves, contactor coil) is separate, final supply TBD (`hardware/power/POWER_AND_WIRING.md`). |

Do not power the board from USB-C and the 7-36 V terminal at the same time until the manual confirms it is safe (open item in `reference/README.md`). Use USB-C only for programming with loads disconnected.

## 3. RS485 to the sensor nodes

Link parameters (from `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`): 19200 8E1, controller = master polling unit ids 1..15 (start with 1 = RO skid, 2 = tank), sensor nodes = servers. Node id comes from each node's DIP switch.

| Main controller `[T]` | Sensor nodes (trunk pins) | Notes |
|---|---|---|
| RS485 A (D+) | RS485 A (D+), pin 4 | Same polarity both ends; vendor label convention may differ from the transceiver chip, confirm with a meter and a scope or by trying the swap on the bench with no loads connected. |
| RS485 B (D-) | RS485 B (D-), pin 5 | Twisted pair. |
| RS485 GND / reference `[T]` | Trunk GND, pins 7 and 8 | GND rides the trunk with the 24 V supply return; no earth bond. Sensor nodes use non-isolated RS485 because the trunk carries common GND (isolated-transceiver footprint is an option; scheme unverified until Stage D). The vendor wiki lists the controller RS485 as isolated (`reference/README.md`); this is a vendor claim, unverified on the bench, and the reference-ground scheme is TBD. |

- **Multi-node trunk:** the RS485 A/B/GND terminals feed an RJ45 trunk jack wired per `hardware/interconnect/pinout.yaml` (A pin 4, B pin 5, GND pins 7 and 8) and a daisy chain of nodes (`hardware/interconnect/NODE_BUS_INTERCONNECT.md`). All `[T]` terminal names remain unverified. Never plug the trunk into the controller's Ethernet port.
- **Termination:** controller has a 120 ohm termination jumper cap (enabled by default per the wiki). Switchable 120 ohm termination is at the two end nodes of the chain only; any other device leaves it off. Rules and TBDs (resistor values, whether the controller cap sits at a chain end): interconnect doc, "Termination and bias".
- **Bias:** at the controller only (one point); resistor values TBD (interconnect doc). The wiki does not say whether the board already biases the bus; confirm on the bench with an idle bus before adding any.
- **Direction control:** the pin map lists only TX GPIO17 and RX GPIO18, which suggests automatic direction control. Unverified; confirm on the bench.
- **Cabling:** shielded Cat5e/Cat6 trunk with RS485 on the twisted pair, keep away from AC motor conductors, shield bonded at the controller end only (interconnect doc, "Shield").
- Do not connect the bus while vendor firmware is loaded, because it transmits Modbus-style relay frames at 9600 8N1 as a master.

## 4. Relay outputs

Each board relay is 1 NO + 1 NC, rated 10 A 250 VAC / 30 VDC on a resistive load. All three loads below are low-power DC; the pump is never switched directly (see K1).

| Relay | Load | Contacts used | Energized | De-energized (reset / power loss) |
|---|---|---|---|---|
| K1 | Booster contactor coil, via the hardwired safety loop (section 5) | COM + NO | Pump enable requested | Pump off |
| K2 | Concentrate bypass valve (normally open motorized ball valve) | COM + NO or NC, depends on actuator | Valve closed for production | Valve open (power-off default, ADR-0002) |
| K3 | Permeate dump solenoid (normally closed) on the tee drain branch | COM + NO | Dump to drain | Valve closed, permeate to tank (ADR-0006) |

### K1: pump contactor (through the safety loop)

```
 +12 V -- F3 --+-- [HP cutoff NC] --+-- [HH level float NC] --+-- K1 COM
               |                    |                         |
               |  (independent hardwired contacts, in series  |
               |   with the coil; wired so opening any of     |
               |   them drops pump enable regardless of K1)   |
               |                                              K1 NO
               |                                               |
               +-------------- contactor coil (12 V) ----------+-- return (12 V -)
                                  |
                       flyback diode across coil
```

- Contactor main contacts, overload, and relief are outside this diagram. They are the motor-rated 120 VAC circuit (`docs/safety/SAFETY_REQUIREMENTS.md`).
- Safety contacts are NC and in series with the coil, so a wire break or tripped switch drops the contactor with the controller disconnected (acceptance test, "Actuators and safety").
- Low feed pressure / dry-run protection also belongs in this loop where the pump design needs it.

### K2: concentrate bypass valve

```
 +12 V -- F2 -- K2 COM
                K2 NO (or NC, per actuator wiring) -- valve actuator -- return (12 V -)
                           flyback diode / suppression per actuator type
```

- Power loss must leave the valve open. The candidate USS-MSV00072 is provisional and may be a two-wire auto-return actuator that is not a simple DC solenoid (`hardware/power/POWER_AND_WIRING.md`); wire per the actuator datasheet. TBD.
- If the actuator is energize-to-close, close it only for production.

### K3: permeate dump valve

```
 +12 V -- F2 -- K3 COM
                K3 NO -- NC solenoid valve coil -- return (12 V -)
                         flyback diode across coil (DC coil)
```

- Coil is energized for the whole dump, which may be minutes at each start; verify coil rating, duty cycle and heating. Valve model TBD.
- Fuse F2 covers both K2 and K3; size to actuator inrush, TBD.

## 5. Protective earth, separation and fusing

- Keep mains (pump contactor main contacts) and the low-voltage rails (24 V, 12 V) physically separated; the board relay contacts only see the valve/coil rail (12 V, final voltage TBD).
- Each branch fused (F1-F4; F4 is the 24 V trunk fuse, fuse per node); values TBD until the loads are identified.
- DC coils get flyback diodes; AC coils would need RC snubbers or varistors instead. The wiki recommends snubbers on inductive loads.

## 6. Open items before bench power-up

1. Read and record the actual terminal labels (`[T]`), then replace each placeholder.
2. Measure relay state at power-on, during reset, in download mode, and with firmware hung (reference README item 3).
3. Confirm RS485 A/B polarity, direction control, and bias.
4. Choose the K2 actuator and confirm the fail-open wiring.
5. Select the NC dump valve and fuse values.
6. Decide the sensor-node RS485 isolation and the reference-ground scheme (non-isolated planned; verify in Stage D).
