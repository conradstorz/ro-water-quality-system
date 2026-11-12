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
- 12V input, 5V buck, 3.3V regulated logic, fuse and transient protection; verify each sensor supply.
## Wiring
Use terminal blocks, labeled signal/ground/supply, strain relief, sensor cable separation from AC motor conductors, and a documented shield/ground scheme. RS485 twisted pair plus suitable reference conductor. No unverified 5V signal into ESP32 3.3V GPIO.
## Mechanical
DIN rail prototype carrier/enclosure with accessible USB programming port and service loop. Waterproofing and condensation mitigation appropriate to utility room.
