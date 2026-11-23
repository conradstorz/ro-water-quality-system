# Sensor node hardware specification
## Proposed modules
- ESP32-S3 dev board with adequate exposed GPIO, UART and I2C; exact board TBD.
- 3.3V-compatible RS485 transceiver; isolation preferred if budget permits; check bus reference, grounding, termination, bias.
- 2 × HX711 interfaces, each with separate data; shared clock optional after testing.
- 2 × conditioned conductivity modules; low-EC range must be verified for permeate; probes are not directly connected to ADC.
- External ADC proposed (ADS1115 or better as justified), correct voltage ranges and protection. ADC resolution does not equal sensor accuracy.
- 2 pulse inputs with level conditioning, input protection, and hardware pulse counting where possible.
- 2 temperature sensor channels, interface TBD until flow meters selected.
- 1 optional analog RO pressure transducer (RO feed: LFT2000 0-16 bar 4-20 mA, ADR-0010); independent hardwired pressure cutoff remains mandatory.
- 24V trunk input via RJ45 (see `hardware/interconnect/NODE_BUS_INTERCONNECT.md`): fuse, reverse-polarity protection, TVS, 5V buck, 3.3V regulated logic; verify each sensor supply. Two parallel RJ45 jacks (IN/OUT).
- Node ID: 4-position DIP switch read at boot, IDs 1-15; duplicate or out-of-range ID leaves the node silent.
## Node types
One carrier board serves all node types; the firmware profile selects the front end.
- RO skid (unit 1, `node_type` 0): 2 × ADS1115 (EC on one, thermistors on the other), 2 pulse inputs on ESP32 PCNT, 2 EC modules, 2 thermistors, RO feed pressure on an ESP32 ADC1 input (ADR-0010).
- Tank (unit 2, `node_type` 1): 2 × HX711 (load cells, 5V excitation), optional pressure; front end (ESP32 ADC1 as on the RO skid, or its ADS1115) TBD (ADR-0010).
## Optional pressure channel (all nodes)
- Decision record: ADR-0010. Monitoring only; the independent hardwired pressure cutoff remains mandatory. Not installed (`installed_mask` bit 6 clear) is not a fault; installed but implausible or lost is.
- RO feed transmitter: LFT2000 (manufacturer to confirm from label), 0-16 bar (232.1 psi full scale), 2-wire 4-20 mA. True supply range, gauge/absolute reference and accuracy class TBD (read the label/order code).
- Loop power: node 24 V trunk, through a per-node loop current limit (value TBD). No separate 12 V supply.
- Input: proposed 120 ohm 0.1 % sense resistor (4-20 mA = 0.48-2.40 V), read directly by an ESP32-S3 ADC1 input at ATTEN3 (0-2900 mV effective range, ESP32-S3 datasheet Table 4-5). Pin: ADC1 (GPIO1-10), exact assignment TBD.
- Protection between sense resistor and pin: series resistor and clamp, values TBD; the clamp must not back-feed the 3.3 V rail.
- Supersedes the earlier 4-20 mA option (250 ohm sense into an ADS1115). The 0.5-4.5 V ratiometric option is undecided (on a direct ESP32 input it needs a divider); TBD.
## 1-Wire front end (all nodes, optional population)
- Monitoring only; never an interlock. See `hardware/interconnect/NODE_BUS_INTERCONNECT.md` and ADR-0009.
- Connector: Nilight 3-pin waterproof male/female harness connector (inline, pigtail through a cable gland). Cavity numbering TBD; voltage and current rating TBD.
- Power: node 5 V rail, non-parasitic, through a polyfuse. Rating TBD.
- Bus driver: one ESP32 GPIO (TBD), series resistor (value TBD), pull-up to 3.3 V (value TBD), ESD/TVS protection on DATA.
- Maximum cable length and device count TBD.
## Wiring
Use terminal blocks, labeled signal/ground/supply, strain relief, sensor cable separation from AC motor conductors, and a documented shield/ground scheme. RS485 twisted pair plus suitable reference conductor. No unverified 5V signal into ESP32 3.3V GPIO.
## Mechanical
DIN rail prototype carrier/enclosure with accessible USB programming port and service loop. Waterproofing and condensation mitigation appropriate to utility room.
