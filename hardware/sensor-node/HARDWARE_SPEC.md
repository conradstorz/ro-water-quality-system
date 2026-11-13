# Sensor node hardware specification
## Proposed modules
- ESP32-S3 dev board with adequate exposed GPIO, UART and I2C; exact board TBD.
- 3.3V-compatible RS485 transceiver; isolation preferred if budget permits; check bus reference, grounding, termination, bias.
- 2 × HX711 interfaces, each with separate data; shared clock optional after testing.
- 2 × conditioned conductivity modules; low-EC range must be verified for permeate; probes are not directly connected to ADC.
- External ADC proposed (ADS1115 or better as justified), correct voltage ranges and protection. ADC resolution does not equal sensor accuracy.
- 2 pulse inputs with level conditioning, input protection, and hardware pulse counting where possible.
- 2 temperature sensor channels, interface TBD until flow meters selected.
- 1 optional analog RO pressure transducer; independent hardwired pressure cutoff remains mandatory.
- 24V trunk input via RJ45 (see `hardware/interconnect/NODE_BUS_INTERCONNECT.md`): fuse, reverse-polarity protection, TVS, 5V buck, 3.3V regulated logic; verify each sensor supply. Two parallel RJ45 jacks (IN/OUT).
- Node ID: 4-position DIP switch read at boot, IDs 1-15; duplicate or out-of-range ID leaves the node silent.
## Node types
One carrier board serves all node types; the firmware profile selects the front end.
- RO skid (unit 1, `node_type` 0): 2 × ADS1115 (EC + pressure on one, thermistors on the other), 2 pulse inputs on ESP32 PCNT, 2 EC modules, 2 thermistors, optional pressure.
- Tank (unit 2, `node_type` 1): 2 × HX711 (load cells, 5V excitation), 1 × ADS1115 for optional pressure.
## Optional pressure channel (all nodes)
- One input with 5V transducer excitation pin, protection network (values TBD), and a spare ADS1115 channel.
- Solder jumper selects 0.5-4.5V ratiometric or 4-20mA (250 ohm sense resistor, loop power from 24V). Transducer model, range and ADC scaling TBD. TBD: ADS1115 supply rail and input scaling/protection for both options (0.5-4.5V and 4-20mA across the 250 ohm sense resistor), since each can reach about 5V, which exceeds an ADS1115 input unless the ADC runs from 5V; no values chosen yet.
- Monitoring only; the independent hardwired pressure cutoff remains mandatory. Not installed is not a fault; installed but implausible or lost is.
## 1-Wire front end (all nodes, optional population)
- Monitoring only; never an interlock. See `hardware/interconnect/NODE_BUS_INTERCONNECT.md` and ADR-0009.
- Connector: Nilight 3-pin waterproof male/female harness connector (inline, pigtail through a cable gland). Cavity numbering TBD; voltage and current rating TBD.
- Power: node 5 V rail, non-parasitic, through a polyfuse. Rating TBD.
- Bus driver: one ESP32 GPIO (TBD), series resistor, pull-up to 3.3 V (value TBD), ESD/TVS protection on DATA.
- Maximum cable length and device count TBD.
## Wiring
Use terminal blocks, labeled signal/ground/supply, strain relief, sensor cable separation from AC motor conductors, and a documented shield/ground scheme. RS485 twisted pair plus suitable reference conductor. No unverified 5V signal into ESP32 3.3V GPIO.
## Mechanical
DIN rail prototype carrier/enclosure with accessible USB programming port and service loop. Waterproofing and condensation mitigation appropriate to utility room.
