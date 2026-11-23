# ADR-0010: RO feed pressure transmitter, 4-20 mA direct to ESP32-S3 ADC

**Status:** Proposed (2026-11-23) — pending owner review and bench verification.

**Decision:** The RO feed pressure channel (RO skid node, validity bit 6, fault bit 5, registers 115 and 131) uses a **Lefoo LFT2000**, 0-16 bar, 2-wire 4-20 mA transmitter. The loop is powered from the node's **24 V trunk** through a current limiter, and the loop current develops a voltage across a 100 Ω sense resistor read **directly by ESP32-S3 GPIO1 (ADC1_CH0)**. The same front end is the optional pressure input on every node type (one carrier board); 4-20 mA is the only supported pressure signal. The channel stays **monitoring only**: bit 6 is not in `critical_validity_bits`, no software pressure trip or warning threshold is defined, and the independent hardwired high-pressure cutoff remains mandatory. No protocol change.

**Facts (owner-supplied):** Lefoo LFT2000, RO feed, 0-16 bar, 2-wire 4-20 mA, 24 V trunk, direct ESP32 ADC input. No other transmitter specifications are known.

## Circuit (per node)
```
+24V trunk (after node fuse / reverse-polarity / TVS)
  -> LM317 current limiter, 43 ohm 1 % OUT-ADJ      I_lim = 1.25 V / 43 ohm = 29 mA (28-30 mA over Vref 1.20-1.30 V)
  -> terminal P+  -> LFT2000 ->  terminal P-
  -> resettable PTC, hold >= 50 mA, trip <= 100 mA, rated >= 30 V
  -> R_sense 100 ohm 0.1 %, >= 0.25 W  -> GND
R_sense top -> 10 kohm -> GPIO1 (ADC1_CH0); 100 nF GPIO1-GND; BAT54S dual Schottky GPIO1 to 3V3 and GND
```
- LM317 package SOT-223 or TO-220 with copper able to dissipate 1 W (worst case 24 V × 30 mA = 0.72 W with the transmitter terminals shorted).
- GPIO1 is ADC1 (ADC2 is restricted while Wi-Fi is active) and not a strapping pin (ESP32-S3 strapping pins: GPIO0, 3, 45, 46), USB (19/20) or JTAG (39-42). It is valid on any ESP32-S3 board that breaks out GPIO1.
- The 100 nF at the pin matches the datasheet ADC test condition (Table 4-5, "external 100 nF capacitor") and, with 10 kΩ, forms a ~160 Hz low-pass against pump noise.

## Why a short is a reading, not damage
- Transmitter terminals or field cable P+ to P- shorted: the LM317 holds the loop at about 29 mA, so R_sense sees about 2.9 V (below the 3.3 V rail) and dissipates 84 mW. The ADC saturates, the firmware reports overrange: `pressure_fault` set, validity bit 6 cleared. Nothing is stressed and the trunk sees at most 30 mA extra.
- Field wire P- shorted to +24 V (bypassing the limiter, a wiring error): the PTC trips. The GPIO sees at most (24 − 3.3 − 0.3) V / 10 kΩ ≈ 2 mA into the clamp, which the 3.3 V rail's own load absorbs (no back-feed rise). Worst case is a replaced R_sense; the ESP32 is protected.
- Open loop, unplugged or dead transmitter: 0 mA, below the live zero: `pressure_fault` (when installed).

## Derived (arithmetic, not measured)
- Full scale 16 bar × 14.5038 = 232.1 psi; `ro_feed_pressure_psi_x10` (u16, max 6553.5 psi) holds it as 2321. psi = (I_mA − 4) / 16 × 232.1.
- 4 mA = 0.40 V, 20 mA = 2.00 V, 20.5 mA = 2.05 V, current limit ≈ 2.9 V. ESP32-S3 ADC effective range at ATTEN3 is 0-2900 mV (`hardware/main-controller/reference/datasheets/Esp32-s3_datasheet_en.pdf`, Table 4-5): the measuring range sits well inside it and the shorted case saturates it.
- Resolution about 0.10 psi per count (2900 mV / 4096 ≈ 0.71 mV; 1.60 V / 232.1 psi ≈ 6.9 mV/psi). Datasheet INL ±8 LSB; accuracy comes from calibration.
- Transmitter voltage at 20 mA: 24 − ~3 (LM317 dropout) − ~0.2 (PTC) − 2.0 (R_sense) ≈ 18.8 V. Published LFT2000 supply ranges (8-36 VDC listing, 10-30 VDC family catalog) both include it, so the unknown exact range does not affect the design. A 12 V loop was rejected because it would leave about 7 V.

## Firmware interpretation (NAMUR NE43, chosen by this project)
- 3.8-20.5 mA: valid; 3.8-4.0 mA clamps to 0 psi (unsigned register).
- Below 3.8 mA or above 20.5 mA: `pressure_fault` (fault bit 5) set, validity bit 6 cleared.
- `installed_mask` bit 6 clear: never a fault, whatever the current.
- ATTEN3 with eFuse curve-fitting calibration and multi-sample averaging; two-point offset/span against a trusted gauge. Gauge vs absolute reference and accuracy class are unknown and do not matter: the offset calibration absorbs a reference offset, and the recorded calibration sets the uncertainty.

**Register semantics:** `pressure_raw_adc` (131) keeps type u16, scale 1, unit counts. On this channel it carries the ESP32-S3 12-bit ADC reading (0-4095) instead of ADS1115 counts. No calibration register depends on its meaning; address, type, scale, signedness and access are unchanged (AGENTS.md rule 2 not triggered).

**Alternatives rejected:**
- 250 Ω sense into an ADS1115 (previous jumper option): 20 mA × 250 Ω = 5 V exceeds the ADS1115 input unless it runs from 5 V; adds a part for a diagnostic channel.
- 0.5-4.5 V ratiometric transducers: the ESP32 ADC uses an internal reference, so ratiometric cancellation is lost; needs a divider; no live zero, so an open wire cannot be told from 0 psi as reliably; 5 V signals near 3.3 V GPIO. Dropped with the solder jumper.
- 12 V loop supply: about 7 V left for the transmitter, below both published minimums.
- Using pressure as a software trip: rule 5 forbids guessing pressure limits, and the hardwired cutoff is the protection.

**Consequences:**
- The ADS1115s no longer carry pressure; the tank node's ADS1115 (fitted only for pressure) is removed from its BOM.
- Bench verification required: limiter current, ADC readings at 4/12/20 mA, shorted-terminal and open-loop behavior (see `docs/test/ACCEPTANCE_TEST_PLAN.md`).
