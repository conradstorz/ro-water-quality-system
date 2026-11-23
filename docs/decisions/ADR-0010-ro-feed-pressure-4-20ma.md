# ADR-0010: RO feed pressure transmitter, 4-20 mA direct to ESP32-S3 ADC

**Status:** Proposed (2026-11-23) — pending owner review and bench verification.

**Decision:** The RO feed pressure channel (RO skid node, validity bit 6, fault bit 5, registers 115 and 131) uses a Lefoo **LFT2000**, 0-16 bar, 2-wire 4-20 mA transmitter. The loop is powered from the node's **24 V trunk** (no separate 12 V supply). The loop current develops a voltage across a precision sense resistor read **directly by an ESP32-S3 ADC1 input** (GPIO1-10), not by an ADS1115. The channel stays **monitoring only**: bit 6 is not in `critical_validity_bits`, no software pressure trip or warning threshold is defined, and the independent hardwired high-pressure cutoff remains mandatory. No protocol change.

**Facts (owner-supplied):** LFT2000, RO feed, 0-16 bar, 2-wire 4-20 mA, 24 V trunk, direct ESP32 ADC input.

**Derived (arithmetic, not measured):**
- Full scale 16 bar × 14.5038 = 232.1 psi; `ro_feed_pressure_psi_x10` (u16, max 6553.5 psi) holds it as 2321.
- Linear transfer: psi = (I_mA − 4) / 16 × 232.1.
- With the proposed 120 Ω sense resistor: 4 mA = 0.48 V, 20 mA = 2.40 V, 20.5 mA = 2.46 V. The ESP32-S3 ADC effective range at ATTEN3 is 0-2900 mV (`hardware/main-controller/reference/datasheets/Esp32-s3_datasheet_en.pdf`, Table 4-5), so the input saturates only above about 24 mA and overrange stays detectable.
- Resolution about 0.09 psi per 12-bit count (2900 mV / 4096 ≈ 0.71 mV; 1.92 V span / 232.1 psi ≈ 8.3 mV/psi). Datasheet INL is ±8 LSB; accuracy is set by calibration, not resolution.
- Supply: published LFT2000 minimum is either 8 V (8-36 VDC listing) or 10 V (10-30 VDC family catalog). At 24 V, after about 2.5-3 V across the sense resistor and protection, the transmitter sees about 21 V, inside either range. A 12 V loop would leave about 9-9.5 V, which fails the 10 V figure; this is why 24 V was chosen.

**Proposed (bench-verify before adoption):**
- Sense resistor 120 Ω, 0.1 %, at least 0.25 W rating.
- Loop current interpretation (NAMUR NE43 chosen by this project; the LFT2000's own under/overrange behavior is undocumented): 3.8-20.5 mA is a valid reading; 3.8-4.0 mA clamps to 0 psi (the register is unsigned); below 3.8 mA (open loop, unpowered transmitter) or above 20.5 mA (short, overrange) sets fault bit 5 `pressure_fault` and clears validity bit 6.
- ADC: ATTEN3 with eFuse curve-fitting calibration, multi-sample averaging; two-point offset/span against a trusted gauge (see `docs/operations/CALIBRATION_AND_MAINTENANCE.md`).

**Required, values TBD (do not guess):**
- Per-node loop current limit. A shorted field cable on 24 V would otherwise drive about 200 mA (about 4.8 W) through 120 Ω, push the sense node toward 24 V, and load the shared trunk that powers every node and RS485.
- Series resistor and clamp from the sense node to the GPIO. A clamp diode into 3.3 V can back-feed the 3.3 V rail; the clamp design must account for it.
- Exact GPIO (constraint only: ADC1, GPIO1-10; ADC2 is restricted while Wi-Fi is active per the datasheet).
- LFT2000 true supply range, gauge vs absolute reference, accuracy class, process connection and order code (read from the label or datasheet).

**Fault vs. not installed:** 0 mA looks the same whether the transmitter is absent or the loop is open. `installed_mask` bit 6 decides: not installed is never a fault; installed and below 3.8 mA is a fault.

**Register semantics:** `pressure_raw_adc` (131) keeps type u16, scale 1, unit counts. On this channel it carries the ESP32-S3 12-bit ADC reading (0-4095) instead of ADS1115 counts. No calibration register depends on its meaning; address, type, scale, signedness and access are unchanged (AGENTS.md rule 2 not triggered).

**Alternatives rejected:**
- 250 Ω sense into an ADS1115 (previous jumper option): 20 mA × 250 Ω = 5 V exceeds the ADS1115 input unless it runs from 5 V; adds a part for a diagnostic channel. Superseded for the 4-20 mA leg.
- 12 V loop supply: marginal or out of spec at 20 mA (see Derived), and needs a regulator the node does not otherwise have.
- Using pressure as a software trip: rule 5 forbids guessing pressure limits, and the hardwired cutoff is the protection.

**Consequences:**
- The RO skid ADS1115 no longer carries pressure. Whether the tank node's ADS1115 (fitted only for optional pressure) is dropped is a BOM decision, TBD.
- The 0.5-4.5 V ratiometric jumper leg is not decided here; on a direct ESP32 input it would need a divider (4.5 V exceeds 2.9 V). TBD.
