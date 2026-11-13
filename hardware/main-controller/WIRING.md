# Main controller wiring (draft, unverified)

Scope: Waveshare `ESP32-S3-ETH-8DI-8RO` main controller. Power input, RS485 to the sensor node, and relays K1 (pump contactor), K2 (concentrate bypass), K3 (permeate dump).

**Status: logical wiring only.** The vendor wiki publishes no terminal-block labels or schematic (`reference/README.md`). Every terminal name marked `[T]` below must be read from the board silkscreen and confirmed with a meter before connecting anything. Do not connect any load until project firmware has replaced the vendor firmware and relay boot state has been measured (reference/README.md "Safety-relevant findings" 1-4).

## 1. Overview

```
                 12 VDC SUPPLY (fused per branch)
                          |
      +-------------------+------------------------+-------------------+
      |                   |                        |                   |
   F1 (board)       F2 (K2 / K3 valves)      F3 (K1 contactor     F4 (sensor node
      |                   |                   coil + safety loop)   12 V input)
      v                   |                        |                   |
+--------------------------------------+            |                   v
| MAIN CONTROLLER (ESP32-S3-ETH-8DI-8RO)|            |            +--------------+
|                                      |            |            | SENSOR NODE  |
|  PWR IN [T] 7-36 V +/-               |            |            | ESP32-S3     |
|                                      |            |            |              |
|  RS485 [T] A  B  GND  ---------------+------------+----------->| RS485 A B REF|
|                                      |   2-wire twisted pair   +--------------+
|  K1 [T] COM / NO  ------------------ +--> safety loop -> contactor coil
|  K2 [T] COM / NO or NC ------------- +--> concentrate bypass valve
|  K3 [T] COM / NO  ------------------ +--> permeate dump valve (NC type)
+--------------------------------------+
```

## 2. Power input

| From | To | Notes |
|---|---|---|
| 12 VDC supply (+) via F1 | Controller PWR IN (+) `[T]` | 7-36 V input. Size F1 for board plus any coil current that rides on it, TBD. |
| 12 VDC supply (-) | Controller PWR IN (-) `[T]` | Common return with the valve and coil supplies; keep it separate from mains earth. |
| 12 VDC via F4 | Sensor node 12 V input | Sensor node has its own 5 V buck and 3.3 V regulation (`sensor-node/HARDWARE_SPEC.md`). |

Do not power the board from USB-C and the 7-36 V terminal at the same time until the manual confirms it is safe (open item in `reference/README.md`). Use USB-C only for programming with loads disconnected.

## 3. RS485 to the sensor node

Link parameters (from `docs/specs/SENSOR_NODE_MODBUS_RS485_SPEC.md`): 19200 8E1, unit 1, controller = master, sensor node = server.

| Main controller `[T]` | Sensor node | Notes |
|---|---|---|
| RS485 A (D+) | RS485 A (D+) | Same polarity both ends; vendor label convention may differ from the transceiver chip, confirm with a meter and a scope or by trying the swap on the bench with no loads connected. |
| RS485 B (D-) | RS485 B (D-) | Twisted pair. |
| RS485 GND / reference `[T]` | Transceiver reference | Third conductor of the pair cable, no earth bond at both ends. Main-controller RS485 is isolated; the sensor node transceiver should be isolated or share the reference deliberately (TBD). |

- **Multi-node trunk:** the RS485 A/B/GND terminals feed an RJ45 trunk jack wired per `hardware/interconnect/pinout.yaml` (A pin 4, B pin 5, GND pins 7 and 8). The bus now serves multiple nodes (unit 1 RO skid, unit 2 tank) in a daisy chain, not a single point-to-point link; the single-node notes in this section apply per the interconnect doc (`hardware/interconnect/NODE_BUS_INTERCONNECT.md`). All `[T]` terminal names remain unverified. Never plug the trunk into the controller's Ethernet port.
- **Termination:** controller end has a 120 ohm termination jumper cap (enabled by default per the wiki). Fit a 120 ohm resistor at the sensor node end only. No other terminations.
- **Bias:** open item. The wiki does not say whether the board biases the bus. Add fail-safe bias at one point only if the bench shows an undriven bus floating.
- **Direction control:** the pin map lists only TX GPIO17 and RX GPIO18, which suggests automatic direction control. Unverified; confirm on the bench.
- **Cabling:** twisted pair, keep away from AC motor conductors, shield terminated at one end (the sensor-node documentation covers the scheme).
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

- Keep mains (pump contactor main contacts) and 12 V low voltage physically separated; the board relay contacts only see 12 V.
- Each branch fused (F1-F4); values TBD until the loads are identified.
- DC coils get flyback diodes; AC coils would need RC snubbers or varistors instead. The wiki recommends snubbers on inductive loads.

## 6. Open items before bench power-up

1. Read and record the actual terminal labels (`[T]`), then replace each placeholder.
2. Measure relay state at power-on, during reset, in download mode, and with firmware hung (reference README item 3).
3. Confirm RS485 A/B polarity, direction control, and bias.
4. Choose the K2 actuator and confirm the fail-open wiring.
5. Select the NC dump valve and fuse values.
6. Decide the sensor-node RS485 isolation and the reference-ground scheme.
