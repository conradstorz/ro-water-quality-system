# ADR-0012: Sensor-node carrier board

**Status:** Proposed (2026-11-23). Pending owner review and Stage D bench verification.

**Decision:** Every sensor node is one carrier board that holds an **Espressif ESP32-S3-DevKitC-1-N8** on headers. The DevKitC carries an **ESP32-S3-WROOM-1-N8** module (8 MB quad flash, no PSRAM). The carrier provides:
- the 24 V trunk input stage and a 5 V buck converter;
- RS485;
- the pulse, 1-Wire, ADS1115, HX711, pressure, DIP-switch, button and LCD front ends.

The module and board are the chosen variant, not provisional. The GPIO map also avoids the octal-PSRAM pins, so a later swap to an R8 board keeps working. Everything here is monitoring hardware: no carrier circuit drives a pump or valve, and the hardwired protections stay independent (AGENTS.md rules 3 and 4).

Datasheets are in `hardware/sensor-node/datasheets/` unless a path says otherwise. The ESP32-S3 documents are in `hardware/main-controller/reference/datasheets/`:
- "WROOM-1 DS": the ESP32-S3-WROOM-1/1U datasheet v1.2;
- "S3 DS": the ESP32-S3 series datasheet v1.6;
- "S3 TRM": the technical reference manual v1.2.

Each value below cites a datasheet table or page, or shows its arithmetic. `host_tools/tests/test_sensor_node_carrier_docs.py` checks the arithmetic.

## 1. Module, board and GPIO map

### Board facts (cited)
**DevKitC-1 user guide v1.1** (`https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html`):
- **Ordering table:** "ESP32-S3-DevKitC-1-N8 (EOL) | ESP32-S3-WROOM-1-N8 | 8 MB | —". The guide marks the N8 board **end of life**. The map below also fits the in-production "ESP32-S3-DevKitC-1-N16R8 | ESP32-S3-WROOM-1 | 16 MB | 8 MB".
- **RGB LED:** "the initial version uses GPIO48, whereas v1.1 uses GPIO38". Both versions are on the market, so neither pin is assigned.
- **Headers:** J1 is 3V3, 3V3, RST, 4, 5, 6, 7, 15, 16, 17, 18, 8, 3, 46, 9, 10, 11, 12, 13, 14, 5V, G. J3 is G, TX, RX, 1, 2, 42, 41, 40, 39, 38, 37, 36, 35, 0, 45, 48, 47, 21, 20, 19, G, G. Every pin assigned below is on a header.
- **Header note:** GPIO35, GPIO36 and GPIO37 are used for "communication between ESP32-S3 and SPI flash/PSRAM memory" on octal-PSRAM modules.
- **Power:** "There are three mutually exclusive ways to provide power to the board": USB, the 5V and G pins, or the 3V3 and G pins. The carrier uses the **5V pin** (section 2).
- **UART0:** TX/RX (GPIO43/44) go to the USB-to-UART bridge, which is a CP2102N in the schematic. That bridge is the console and flashing port, so RS485 uses UART1 on other pins.
- **Boot:** the Boot button is the download button, on GPIO0 (a strapping pin).
- **Schematic:** `SCH_ESP32-S3-DevKitC-1_V1.1_20221130.pdf`.
  - The 3.3 V regulator is **U2 SGM2212-3.3XKC3G/TR**.
  - Each USB VBUS reaches VCC_5V through a **1N5819HW-7-F** Schottky diode (D1, D7).
  - No 32.768 kHz crystal is fitted, so GPIO15 and GPIO16 are free.

**Module facts (WROOM-1 DS):**
- **Table 3, note b:** in variants that embed ESP32-S3R8, "pins IO35, IO36, and IO37 connect to the OSPI PSRAM and are not available for other uses".
- **Table 3 pin list:** the module brings out GPIO0-21 and 35-48 only. GPIO22-34 are not on module pins; the in-package flash and PSRAM use them (S3 DS Table 2-14).
- **Strapping pins** (section 3.3, Table 4): GPIO0, 3, 45, 46.
- **JTAG:** MTCK, MTDO, MTDI and MTMS are GPIO39-42 (Table 3).
- **USB:** USB_D-/D+ are GPIO19/20 (Table 3).
- **GPIO47/48 voltage:** S3 DS Table 2-1, note 5, says they run at 1.8 V only on the **ESP32-S3R8V** chip. WROOM-1 v1.2 Table 1 lists no R8V variant, so GPIO47 is a 3.3 V pin on N8 and on R8 modules.

**Power-up glitches (S3 DS Table 2-2):**
- GPIO1-14, XTAL_32K_P/N (GPIO15/16) and GPIO17 show a 60 µs low-level glitch at power-up.
- GPIO18 shows a 60 µs **high**-level glitch.
- GPIO19/20 also glitch.
- GPIO21 and GPIO47 are not listed.

**Pulse counters:** S3 TRM chapter 38 says the PCNT "has four independent pulse counters called units", each with two channels and a glitch filter. Two units are used.

### Excluded pins
| Excluded | Reason |
|---|---|
| 0, 3, 45, 46 | Strapping (WROOM-1 DS Table 4); GPIO0 is also the DevKitC Boot button |
| 19, 20 | USB D-/D+ (WROOM-1 DS Table 3) |
| 39, 40, 41, 42 | JTAG (WROOM-1 DS Table 3) |
| 43, 44 | UART0 to the DevKitC USB-to-UART bridge (console, flashing) |
| 35, 36, 37 | Octal PSRAM on R8 variants (WROOM-1 DS Table 3 note b) |
| 38, 48 | DevKitC RGB LED, v1.1 and v1.0 respectively (user guide) |
| 22-34 | Not on module pins; in-package flash/PSRAM (S3 DS Table 2-14) |

That leaves 19 usable pins: GPIO1, 2, 4-18, 21 and 47. The map uses 18 of them and keeps GPIO2 as a spare ADC1 input.

### GPIO map (normative copy: `hardware/sensor-node/pinout.yaml`)
| GPIO | Signal | Direction | Notes |
|---|---|---|---|
| 1 | PRESSURE_ADC | analog in | ADC1_CH0, ADR-0010 |
| 2 | SPARE_ADC | analog in | ADC1_CH1, test pad only, not connected |
| 4 | NODE_ID_0 | in | DIP switch 1 (bit 0), 10 kΩ pull-up |
| 5 | NODE_ID_1 | in | DIP switch 2 (bit 1) |
| 6 | NODE_ID_2 | in | DIP switch 3 (bit 2) |
| 7 | NODE_ID_3 | in | DIP switch 4 (bit 3) |
| 8 | I2C_SDA | open drain | ADS1115 ×2, DS2482-100, PCA9306 to LCD |
| 9 | I2C_SCL | open drain | same bus, 100 kHz |
| 10 | BTN_NEXT | in | diagnostic button 1 |
| 11 | HX711_A_DOUT | in | tank load cell A |
| 12 | HX711_A_SCK | out | low glitch only (Table 2-2), harmless |
| 13 | HX711_B_DOUT | in | tank load cell B |
| 14 | HX711_B_SCK | out | low glitch only, harmless |
| 15 | PULSE_PERMEATE | in | PCNT unit 0 |
| 16 | PULSE_CONCENTRATE | in | PCNT unit 1 |
| 17 | RS485_TX | out | UART1 TXD (IO MUX default, WROOM-1 DS Table 3) |
| 18 | RS485_RX | in | UART1 RXD; the high glitch is an input-side concern only (section 3) |
| 21 | RS485_DE_RE | out | not in Table 2-2; 10 kΩ pull-down keeps the driver off at boot |
| 47 | BTN_HOLD | in | diagnostic button 2; 3.3 V on WROOM-1 N8/R8 |

- **Analog signals:** the only analog signals are on ADC1 (GPIO1, and the spare GPIO2). EC and thermistors use the ADS1115s, so no ADC2 pin is needed while Wi-Fi is active.
- **Status LED:** the DevKitC's own RGB LED is the status LED. Firmware drives GPIO38 or GPIO48 according to the board revision. The carrier adds no LED pin.
- **I²C addresses:** DS2482-100 is 0x18 (DS2482-100 datasheet Figure 9, AD1 = AD0 = 0). The ADS1115s are 0x48 and 0x49 (ADS1115 Table 7-2: ADDR to GND gives 1001000b, ADDR to VDD gives 1001001b). The PCF8574 LCD backpack is in the 0x20-0x27 range, or 0x38-0x3F for the "A" part. No address collides.
- **Bus speed:** the bus runs at 100 kHz because the PCF8574 fSCL maximum is 100 kHz (PCF8574 datasheet, Timing Requirements).

## 2. Trunk input stage and power

```
RJ45 IN/OUT +24V (pins 1,2) -- F1 Bourns MF-R065 PTC -- D1 onsemi MBRS3100T3G (anode->cathode) --+-- 24V_PROT
                                                                                                  |
                                                                       TVS1 Bourns SMBJ33A to GND
24V_PROT -> pressure loop LM317 (ADR-0010), flow-meter supply jumper (section 4)
24V_PROT -> U1 TI LMR36015ARNXR buck, 400 kHz, 5.0 V:
            RFBT 100 kΩ / RFBB 24.9 kΩ, L 10 µH, COUT 3 × 22 µF, CIN 4.7 µF + 2 × 220 nF, CFF 20 pF
            (LMR36015 Table 10-1 and section 10.2 design example, 5 V / 400 kHz row)
5V_CARRIER -> LCD, EC modules, HX711 VCC, 1-Wire +5V, pulse pull-ups, PCA9306 5 V side
5V_CARRIER -- D2 Diodes 1N5819HW-7 -- DevKitC 5V pin -> SGM2212-3.3 (on DevKitC) -> 3V3 pin
3V3 (from DevKitC 3V3 pin) -> RS485, ADS1115, DS2482, HX711 DVDD, LVC2G17, PCA9306 3.3 V side, pull-ups
```
- **Fuse:** F1 is a Bourns **MF-R065** resettable PTC, rated 60 V Vmax, 0.65 A hold and 1.30 A trip at 23 °C (MF-R datasheet Rev. AR, electrical table). At 50 °C ambient it is rated 0.47 A hold, at 60 °C 0.41 A (thermal derating table). Sizing is in section 2.1.
- **Reverse polarity:** D1 is an onsemi **MBRS3100T3G**, a series Schottky: 100 V VRRM, 3.0 A, VF max 0.79 V at 3 A and 25 °C (datasheet Rev. 8, Maximum Ratings and Electrical Characteristics). A reversed supply is blocked, not crowbarred.
- **TVS:** TVS1 is a Bourns **SMBJ33A** (SMBJ datasheet Rev. 09/20): VRWM 33 V, VBR 36.7-40.6 V, VC 53.3 V at IPP 11.3 A (10/1000 µs), 600 W.
  - The LMR36015's VIN absolute maximum is 66 V (Absolute Maximum Ratings), which is above 53.3 V.
  - Recorded gap: the ADR-0010 LM317 has a 40 V input-to-output absolute maximum (LM317 datasheet SLVS044Z, Absolute Maximum Ratings). With the pressure terminals shorted and a full surge at the same time, it would see 53.3 − 2.9 = 50.4 V. Normal shorted-loop operation is 24 − 2.9 = 21.1 V. This double fault is accepted for a monitoring channel; a 60 V-rated limiter is the upgrade path.
- **Buck converter:** U1 is a TI **LMR36015ARNXR**: 4.2-60 V input, 1.5 A, "90% efficiency at 400 kHz (24 VIN, 5 VOUT, 1 A)" (Features). With RFBT 100 kΩ and RFBB 24.9 kΩ (Table 10-1), it gives 5.0 V.
- **3.3 V regulator:** the regulator is the DevKitC's **SGM2212-3.3**, rated 800 mA output (SGM2212 datasheet Rev. A.2, Features).
  - Its dropout at 800 mA is at most 450 mV (Electrical Characteristics), and its SOT-223 θJA is 117 °C/W (Package Thermal Resistance).
  - WROOM-1 DS Table 10 requires an external supply able to deliver at least 0.5 A. 800 mA meets that.
  - The carrier has **no second 3.3 V regulator**. Its 3.3 V loads hang on the DevKitC 3V3 pin, and no regulator is paralleled onto it.
- **5 V feed (D2):** D2 is a **1N5819HW-7**: 40 V, 1.0 A, VF max 450 mV at 1 A (DS30217 Product Summary). It feeds the DevKitC 5V pin.
  - The DevKitC's own D1/D7 stop the carrier back-feeding the PC.
  - D2 stops USB-only power (bench flashing) from back-feeding the buck output and the field loads.
  - LDO headroom: 5.0 − 0.45 = 4.55 V ≥ 3.3 + 0.45 = 3.75 V.
  - Whether USB and the 5V pin may be live together is left as a bench check, because the user guide calls the supply options mutually exclusive (Stage D).
- **LDO thermal limit:** the worst case ignores D2's drop, so the SGM2212 input is 5.0 V.
  - With Wi-Fi off, the 3V3 load is 208.1 mA: 355.0 is replaced by 107.9 mA, the WROOM-1 DS Table 13 maximum at 240 MHz, dual core, all peripheral clocks on. The LDO then dissipates (5.0 − 3.3) × 0.2081 = 0.354 W, a 41.4 °C rise.
  - With continuous Wi-Fi TX (455.2 mA) it would dissipate 0.774 W, a 90.5 °C rise.
  - **Rule:** production firmware keeps Wi-Fi off, or at a low duty cycle that a Stage D thermal check confirms. The Wi-Fi peak is used only for fuse and regulator sizing.

### 2.1 Per-node current budget
All front ends are counted as populated, which is conservative for both node types. Rows marked **allowance** are design allowances for owner-supplied parts, not datasheet facts. Replace them when the parts are known.

| Load | Rail | mA | Basis |
|---|---|---|---|
| ESP32-S3-WROOM-1, Wi-Fi TX peak (802.11b, 20.5 dBm) | 3V3 | 355.0 | WROOM-1 DS Table 12 |
| THVD1450 driving 54 Ω: ICC 3.0 + 3.3 V / 54 Ω | 3V3 | 64.1 | THVD1450 Table 7.7 ICC max; VOD ≤ VCC |
| ADS1115 ×2, 0.3 mA max each | 3V3 | 0.6 | ADS1115 Electrical Characteristics, IVDD |
| HX711 DVDD ×2, 0.1 mA each | 3V3 | 0.2 | HX711 Table 2, digital supply current |
| DS2482-100 ICC | 3V3 | 0.8 | DS2482-100 Electrical Characteristics, 0.75 mA max |
| 1-Wire pull-up with the line low, 3.3 V / 1000 Ω | 3V3 | 3.3 | DS2482-100 RWPU min 1000 Ω |
| I²C pull-ups, 2 × 3.3 V / 4.7 kΩ | 3V3 | 1.4 | arithmetic |
| DIP, button, RX and DE resistors, 8 × 3.3 V / 10 kΩ | 3V3 | 2.6 | arithmetic |
| Thermistor reference resistors, 2 × 1.0 (allowance, Rref ≥ 3.3 kΩ) | 3V3 | 2.0 | allowance |
| 3V3 reference divider on ADS1115 #2, 3.3 V / 20 kΩ | 3V3 | 0.2 | arithmetic |
| DevKitC on-board LEDs and bridge (allowance) | 3V3 | 25.0 | allowance |
| **3V3 total** | 3V3 | 455.2 | sum |
| DevKitC 5V pin: the 3V3 total through the SGM2212 | 5V | 455.2 | linear regulator: I_in ≈ I_out |
| LCD module with backlight (allowance; owner part) | 5V | 150.0 | allowance |
| HX711 analog supply ×2, 1.4 mA each | 5V | 2.8 | HX711 Table 2, analog supply current incl. regulator |
| Load-cell excitation ×2, 4.30 V / 350 Ω (allowance; bridge resistance is an owner fact) | 5V | 24.6 | allowance |
| EC modules ×2, 50 mA each (allowance; owner part) | 5V | 100.0 | allowance |
| 1-Wire devices (allowance; DS18B20 IDD is 1.5 mA max, 8 × 1.5 = 12) | 5V | 50.0 | allowance |
| Pulse open-collector pull-ups, 2 × 5 V / 4.7 kΩ | 5V | 2.1 | arithmetic |
| **5V total** | 5V | 784.7 | sum |
| Buck input: 5.0 V × 0.7847 A / 0.85 / (24 − 0.79) V | 24V | 198.9 | η 0.85 is below the cited 90 % point; D1 VF 0.79 V |
| Pressure loop, 1.30 V / 43 Ω | 24V | 30.2 | ADR-0010, LM317 Vref max |
| Flow-meter supply, 2 × 25 mA (allowance; owner part) | 24V | 50.0 | allowance |
| **24V total** | 24V | 279.1 | sum |

- **Per node:** 279.1 mA from 24 V. The earlier "<200 mA" assumption is replaced. At an 18 V node input, the buck draws 4.616 W / 17.21 V = 268.2 mA, so the total is 348.4 mA.
- **Fuse margin:** the MF-R065 holds 0.47 A at 50 °C, which is 0.47 / 0.2791 = 1.68 × the 24 V budget. At 60 °C it holds 0.41 A (1.47 ×). It also exceeds the 18 V case. The design ambient of 50 °C inside the enclosure is a design choice; check it in Stage D.
- **Controller trunk fuse F4:** size it for the sum of the node budgets (two nodes: 558.2 mA). F4 itself is outside this ADR.

## 3. RS485 (non-isolated; GND rides the trunk, ADR-0008)
```
GPIO17 -> D       THVD1450DR (SOIC-8), VCC = 3V3      A -> RJ45 pin 4 (IN and OUT in parallel)
GPIO18 <- 1 kΩ <- R,  10 kΩ pull-up to 3V3 at GPIO18  B -> RJ45 pin 5
GPIO21 -> DE and /RE tied, 10 kΩ pull-down             TVS2 Littelfuse SM712-02HTG: A and B to GND
                                                       R_T 120 Ω 1 % 0.25 W across A-B through jumper J_TERM
```
- **Transceiver:** TI **THVD1450DR**, VCC 3-5.5 V (Recommended Operating Conditions).
  - "Open, Short, and Idle Bus Failsafe" (Features). The receiver output goes failsafe-high when the bus is open, shorted or idle (section 9 Receiver Function Table).
  - VTH+ is at most −20 mV and VTH− at least −200 mV (Electrical Characteristics), so a 0 V idle bus reads as a valid high.
  - 1/8 unit load. Bus pins are rated −18 to 18 V absolute maximum. ESD is ±18 kV IEC 61000-4-2 contact.
- **DE and /RE:** tied together on GPIO21, which has no power-up glitch (S3 DS Table 2-2). The 10 kΩ pull-down holds the driver off and the receiver on during reset.
- **RX pull-up:** /RE high leaves R high-impedance (Receiver Function Table), so a 10 kΩ pull-up keeps UART1 RX idle while the node transmits.
- **RX series resistor:** the 1 kΩ in R limits contention during GPIO18's 60 µs high glitch at power-up to 3.3 mA.
- **TVS on A/B:** Littelfuse **SM712-02HTG** (datasheet revised 08/22/19).
  - Working voltage −7 V to 12 V, matching the RS485 common-mode range.
  - IEC 61000-4-2 ±30 kV contact; 19 A 8/20 µs surge; VC 19 V at 1 A and 31 V at 19 A (Electrical Characteristics).
  - Recorded gap: above about 1 A of surge, the clamp exceeds the THVD1450's ±18 V bus absolute maximum. The trunk runs indoors in a utility room, and the transceiver's own IEC ESD rating covers ESD.
- **Termination:**
  - 120 Ω across A-B through a 2-pin jumper. Power at VOD = 3.3 V is 3.3² / 120 = 91 mW, within 0.25 W.
  - The **controller is the head of the chain, so its 120 Ω jumper cap stays on**.
  - The **far-end node fits J_TERM**. Every intermediate node leaves it off.
  - Exactly two terminations: 120 ∥ 120 = 60 Ω.
- **Bias:** the nodes need none, because their receivers are failsafe. Bias would help only the controller's receiver, whose transceiver is unknown.
  - Bias, if the Stage D idle-bus check shows it is needed, goes **at the controller end only**: a pull-up on A and a pull-down on B.
  - The idle differential is Vb × 60 / (2R + 60). It must reach the 200 mV threshold magnitude that TIA/EIA-485 receivers may have (the THVD1450 VTH− minimum is −200 mV).
  - From 3.3 V: R ≤ (3.3 × 60 / 0.2 − 60) / 2 = 465 Ω. **390 Ω** gives 3.3 × 60 / 840 = 236 mV.
  - From 5 V: R ≤ 720 Ω. **680 Ω** gives 5 × 60 / 1420 = 211 mV.
  - Fit nothing until the bench shows the controller needs it.

## 4. Pulse inputs (permeate, concentrate)
One universal front end per channel: open-collector or open-drain outputs, or 5-24 V push-pull outputs. It is not isolated; the meter is powered from the node.
```
F+  <- jumper JP_SUPPLY: 5V_CARRIER or 24V_PROT, through Bourns MF-R010 PTC
SIG -- TVS3 Bourns SMAJ33A to GND
SIG -- [JP_OC fitted for open collector/drain] 4.7 kΩ to 5V_CARRIER
SIG -- R1 10 kΩ 0.25 W -- node N -- R2 22 kΩ to GND
                          N -- BAT54S (Diodes BAT54S-7) clamp to 3V3 and GND
                          N -- 1 nF to GND
                          N -> SN74LVC2G17DBVR Schmitt buffer (VCC 3V3) -> GPIO15 / GPIO16 (PCNT)
GND
```
Thresholds come from the SN74LVC2G17 datasheet (SCES381O, Electrical Characteristics). At VCC = 3 V, VT+ max is 2.0 V and VT− min is 0.8 V; at 4.5 V, VT+ max is 3.1 V. Interpolating to 3.3 V gives VT+ max = 2.0 + 0.3 / 1.5 × 1.1 = 2.22 V. The input VI is rated up to 5.5 V (Recommended Operating Conditions).
- **Divider ratio:** 22 / 32 = 0.6875.
- **Minimum push-pull high:** 2.22 / 0.6875 = 3.23 V, so a 5 V output qualifies.
- **Maximum push-pull low:** 0.8 / 0.6875 = 1.16 V.
- **Open collector with JP_OC fitted:** high is 5 × 22 / 36.7 = 3.00 V. With the 5 V rail at 4.75 V it is 2.85 V. Both are above 2.22 V. The output must sink 5 V / 4.7 kΩ = 1.06 mA.
- **24 V push-pull:** N would be 16.5 V unclamped. It is clamped at 3.3 + 0.40 = 3.70 V; BAT54S VF max is 400 mV at 10 mA (DS11005 Electrical Characteristics). 3.70 V is below VI max 5.5 V.
  - Clamp current is (24 − 3.70) / 10 k − 3.70 / 22 k = 1.86 mA, well under BAT54S IO 200 mA. The 3V3 rail's load, at least 107.9 mA, absorbs it.
  - At the TVS working voltage of 33 V: 2.93 mA, and R1 dissipates 86 mW.
- **24 V on SIG with JP_OC fitted (miswire):** (24 − 5) / 4.7 kΩ = 4.0 mA back into the 5 V rail, which its load absorbs.
- **Filtering:** RC 6.9 kΩ × 1 nF = 6.9 µs. The PCNT glitch filter (S3 TRM chapter 38) is set in firmware.
- **Meter supply:** the F+ PTC is a Bourns MF-R010: 0.10 A hold at 23 °C, 0.07 A at 50 °C, 60 V.
- **Open owner fact:** the flow-meter output type, voltage and supply voltage set JP_OC and JP_SUPPLY. The circuit covers all the listed cases; it does not cover a 3.3 V-only push-pull output, whose high level is below 3.23 V.

## 5. 1-Wire front end (ADR-0009)
**Decision:** use a **DS2482S-100+ I²C 1-Wire master**, not a bare GPIO.
- **Cited reasoning:**
  - The DS2482-100 datasheet (REV 061208, Active Pullup section) says "Active Pullup should be selected if the 1-Wire line has a substantial length (several 10m)". The chain is daisy-chained through inline plugs, and its length is unknown until Stage D.
  - The connector cavities are TBD, so a +5V-to-DATA miswire is credible. The DS2482 "Voltage Range on Any Pin" is −0.5 V to +6 V (Absolute Maximum Ratings).
  - An ESP32 GPIO is limited to VDD + 0.3 V (WROOM-1 DS Table 11, VIH max). A 5 V DATA line on a GPIO would exceed it.
- **Other benefits:** timing is done in hardware, so there is no bit-banging under Wi-Fi or RTOS interrupts. The DS2482 also frees one GPIO; the map in section 1 has no spare for a 1-Wire pin otherwise.
- **Circuit:**
  - DS2482S-100+: VCC 3V3 (the 3.3 V option is 2.9-3.7 V), AD0 = AD1 = GND (**0x18**), SLPZ to VCC, PCTLZ not connected. It sits on the shared I²C bus.
  - IO goes through a **33 Ω** series resistor to connector DATA.
  - **Pull-up:** the internal RWPU of 1000-1675 Ω, with APU enabled in firmware. An external pull-up footprint is left unfitted.
  - **ESD:** a TI **TPD1E10B06DPYR** from DATA to GND at the connector, operating ±5.5 V, IEC 61000-4-2 ±30 kV (SLLSEB1G, ESD Ratings and Recommended Operating Conditions). A second TPD1E10B06 goes from +5V to GND.
  - **Power:** connector +5V is 5V_CARRIER through a Bourns **MF-R010** polyfuse (0.10 A hold and 0.20 A trip at 23 °C; 0.07 A hold at 50 °C; 60 V). Power is non-parasitic.
- **Arithmetic:**
  - Pull-up current: at most 3.3 V / 1000 Ω = 3.3 mA. That is within the 4 mA at which DS2482 VOL1 is specified (0.4 V), within the DS18B20 sink current of 4.0 mA at 0.4 V, and well under the DS2482 ±20 mA pin absolute maximum.
  - Low level: 0.4 + 3.3 mA × 33 Ω = 0.51 V. That is below the DS18B20 VIL max of 0.8 V and the DS2482 VIL1 max of 0.9 V at 3.3 V.
  - High level: 3.3 V, above the DS18B20 VIH min of 2.2 V and the DS2482 VIH1 of 1.9 V. DATA therefore stays 3.3 V-safe while the devices run from 5 V.
  - The DS18B20 figures are from the DS18B20 datasheet, DC Electrical Characteristics. The repo copy is a Dallas preliminary edition; recheck it against the current Analog Devices revision.
  - The polyfuse holds 0.07 A at 50 °C, above the 50 mA allowance and the 12 mA DS18B20 figure.
- **Recorded residual:** with +5V shorted onto DATA while the DS2482 drives low, the IO current is about 5 V / 33 Ω = 150 mA, which exceeds the ±20 mA absolute maximum. Firmware stops issuing 1-Wire resets once the DS2482 short-detect bit is set. The MF-R010 trips at 0.14 A at 50 °C. The 8-pin DS2482 is the sacrificial part, and the ESP32 is not exposed.
- **Connector cavity numbering stays TBD** (owner part, Nilight connector).

## 6. ADS1115 and HX711
- **ADS1115s:** two TI **ADS1115IDGSR** at VDD = 3V3. #1 (EC) has ADDR to GND (**0x48**); #2 (thermistors) has ADDR to VDD (**0x49**).
  - Absolute maximum: the analog inputs must stay within GND − 0.3 V to VDD + 0.3 V, with ±10 mA continuous input current (ADS1115 Absolute Maximum Ratings).
  - Firmware uses FSR ±4.096 V. The common-mode input impedance there is 6 MΩ (Electrical Characteristics).
- **EC inputs (#1 AIN0 feed, AIN1 permeate; AIN2/3 spare):**
  - Circuit: EC_OUT, then 10 kΩ, to node N; 10 kΩ from N to GND; BAT54S clamp at N to 3V3/GND; 100 nF at N; 1 kΩ from N to AIN.
  - **The divider of 0.5 is fitted by default** because the EC module output range is unknown (owner fact).
  - Up to 5.5 V input, N stays at or below 2.75 V. That is below VDD = 3.3 V, so the clamp never conducts in range.
  - A 24 V fault puts at most (24 − 3.7) / 10 k = 2.0 mA into the clamp. The ADS1115 input current is limited further by the 1 kΩ.
  - The source impedance of 5 kΩ against 6 MΩ is a 0.08 % gain error, which calibration removes.
  - A module whose output exceeds 5.5 V needs a new top resistor (open fact).
- **Thermistor inputs (#2 AIN0, AIN1):**
  - Circuit: Rref from 3V3 to terminal T+, thermistor from T+ to T− (GND), and 10 kΩ from T+ to AIN, with a BAT54S clamp and 100 nF at AIN.
  - #2 AIN2 reads the 3V3 rail through a 10 kΩ / 10 kΩ divider (1.65 V), so firmware computes the thermistor ratiometrically.
  - A 24 V fault on T+ gives (24 − 3.7) / 10 k = 2.0 mA into the clamp.
  - Rref equals the thermistor's nominal resistance, which is an owner fact. The budget allows 1 mA per channel (Rref ≥ 3.3 kΩ).
- **HX711, digital supply:** the datasheet allows the digital supply DVDD to be 2.6-5.5 V and VSUP 2.7-5.5 V (Pin Description). It says "Digital power supply (DVDD) should be the same power supply as the MCU power supply" (Power Supply Options). **DVDD = 3V3**, so DOUT never exceeds 3.3 V.
- **HX711, analog supply:** VSUP = 5 V. AVDD comes from the on-chip regulator: "VAVDD = VBG × (R1 + R2) / R1 … designed with a minimum of 100 mV below VSUP voltage".
- **Approved part:** a **SparkFun Load Cell Amplifier HX711** board (schematic v11, `SparkFun_HX711_Load_Cell_v11_schematic.pdf`).
  - It brings out **VCC** (analog/regulator) and **VDD** (digital logic) separately.
  - Its MMBT4403 regulator with 20 kΩ / 8.2 kΩ sets AVDD = 1.25 × 28.2 / 8.2 = **4.30 V**, which is ≤ 5.0 − 0.1 V.
  - Its solder jumper **SJ2 (VCC-VDD) must be open**. Confirm with a meter that VCC and VDD are not connected before connecting the ESP32.
  - Boards that tie VCC and VDD together would put 5 V on DOUT and are not allowed.
  - An on-board equivalent copies the same circuit (PNP, 20 kΩ / 8.2 kΩ, DVDD on 3V3).
- **Spec correction:** excitation is AVDD = 4.30 V, not "5V excitation" as the previous spec said.

## 7. DIP switch, LCD and buttons
- **DIP switch:** a 4-position SPST DIP switch from GPIO4-7 to GND, each with a 10 kΩ pull-up to 3V3 (0.33 mA when ON). ON reads 0; firmware inverts it to the ID bit. The ESP32's internal 45 kΩ pull-ups (WROOM-1 DS Table 11) are not relied on.
- **LCD:** the PCF8574 VIH is 0.7 × VCC (PCF8574 datasheet, Recommended Operating Conditions), which is 3.5 V on a 5 V backpack. A 3.3 V ESP32 cannot drive that reliably, and the backpack's pull-ups may sit at 5 V. So the LCD goes through a TI **PCA9306DCUR** translator:
  - VREF1 = 3V3; VREF2 to 5V_CARRIER through **200 kΩ**, with EN tied to VREF2 (PCA9306 section 9.2, Figure 9-1; "3.3-V VREF1 and 5-V VREF2" is a supported pairing).
  - 4.7 kΩ pull-ups on the 3.3 V side. These are the bus pull-ups: 3.3 / 4.7 k = 0.70 mA, against the ESP32's 28 mA IOL (WROOM-1 DS Table 11).
  - 4.7 kΩ to 5 V on the LCD side, fitted only if the backpack has none.
  - LCD connector: GND, +5V, SDA5, SCL5.
- **Buttons (NEXT on GPIO10, HOLD on GPIO47):** momentary NO switch to GND through 100 Ω.
  - 10 kΩ pull-up to 3V3 and 100 nF to GND at the switch node, then 1 kΩ to the GPIO. A TPD1E10B06 sits at the button connector.
  - RC τ = 10 kΩ × 100 nF = 1.0 ms. The level rises to VIH (0.75 × VDD, WROOM-1 DS Table 11) after τ × ln 4 = 1.39 ms.
  - Pressed level: 3.3 × 100 / 10100 = 33 mV. Discharge peak: 3.3 V / 100 Ω = 33 mA.
  - The 20 ms debounce and the stuck-button timeout stay in firmware (`docs/TODO.md`).
  - Buttons are display-only and have no authority (TODO "Authority limits").

## 8. Carrier BOM (per node)
| Ref | Part number | Value / rating | Purpose |
|---|---|---|---|
| A1 | Espressif ESP32-S3-DevKitC-1-N8 (EOL; drop-in ESP32-S3-DevKitC-1-N16R8) | ESP32-S3-WROOM-1-N8 | MCU board on headers |
| J1, J3 | 2 × 22-pin 2.54 mm female header | to match DevKitC J1/J3 | DevKitC socket |
| F1 | Bourns MF-R065 | 0.65 A hold, 1.30 A trip, 60 V | node fuse |
| D1 | onsemi MBRS3100T3G | 100 V 3 A Schottky | reverse polarity |
| TVS1 | Bourns SMBJ33A | VRWM 33 V, 600 W | trunk surge |
| U1 | TI LMR36015ARNXR | 60 V 1.5 A buck, 400 kHz | 24 V to 5 V |
| L1, C, R | per LMR36015 Table 10-1 | 10 µH; 3 × 22 µF; 4.7 µF + 2 × 220 nF; 100 kΩ / 24.9 kΩ; 20 pF | buck components |
| D2 | Diodes 1N5819HW-7 | 40 V 1 A Schottky | 5 V to DevKitC 5V pin, no back-feed |
| U2 | TI THVD1450DR | 3.3 V RS485, failsafe | transceiver |
| TVS2 | Littelfuse SM712-02HTG | −7/+12 V | RS485 A/B protection |
| R_T, J_TERM | 120 Ω 1 % 0.25 W + 2-pin jumper | 120 Ω | switchable termination |
| R | 10 kΩ (DE pull-down, RX pull-up), 1 kΩ (RX series) | | RS485 logic |
| U3 | TI SN74LVC2G17DBVR | dual Schmitt buffer | pulse inputs |
| TVS3, TVS4 | Bourns SMAJ33A | VRWM 33 V | pulse SIG surge |
| R | 10 kΩ 0.25 W, 22 kΩ, 4.7 kΩ + JP_OC, 1 nF | | pulse dividers and pull-ups |
| F2, F3 | Bourns MF-R010 | 0.10 A hold, 60 V | flow-meter supply |
| JP_SUPPLY ×2 | 3-pin jumper | 5 V / 24 V | flow-meter supply select |
| U4 | Maxim/ADI DS2482S-100+ | 0x18 | 1-Wire master |
| R | 33 Ω | | 1-Wire series |
| F4 | Bourns MF-R010 | 0.10 A hold, 60 V | 1-Wire +5V polyfuse |
| ESD1-ESD4 | TI TPD1E10B06DPYR | ±5.5 V | 1-Wire DATA, 1-Wire +5V, 2 buttons |
| U5, U6 | TI ADS1115IDGSR | 0x48, 0x49 | EC and thermistor ADC |
| D3-D10 | Diodes BAT54S-7 | 30 V 200 mA | clamps: 2 pulse, 2 EC, 2 thermistor, pressure (ADR-0010), spare |
| R, C | 10 kΩ, 1 kΩ, 100 nF; Rref (owner fact) | | ADC dividers and filters |
| A2, A3 | SparkFun Load Cell Amplifier HX711 (SJ2 open), or on-board equivalent | AVDD 4.30 V | load cells (tank node) |
| U7 | TI PCA9306DCUR | 3.3 V / 5 V I²C | LCD level shift |
| R | 4.7 kΩ ×2 (3.3 V side), 4.7 kΩ ×2 unfitted (5 V side), 200 kΩ | | I²C pull-ups and PCA9306 bias |
| SW1 | 4-position SPST DIP switch | | node ID |
| R | 10 kΩ ×4 | | DIP pull-ups |
| R, C | 10 kΩ, 100 Ω, 1 kΩ, 100 nF (×2) | | button debounce |
| Pressure | LM317, 43 Ω, Bourns MF-R005 (0.05 A hold, 0.10 A trip, 60 V), 100 Ω 0.1 %, 10 kΩ, 100 nF, BAT54S | | ADR-0010 loop; MF-R005 meets its PTC rule |
| J_RJ45 ×2 | shielded RJ45, red | IN and OUT in parallel | trunk (ADR-0008) |
| TB | pluggable terminal blocks | | field wiring (section 9) |

## 9. Enclosure and connectors
- **Enclosure class:** a DIN-rail electronics housing for a utility room, with cable glands and condensation mitigation. The DevKitC's USB ports must be reachable for service. **The enclosure model and all mechanical dimensions are TBD**; no dimension is cited here.
- **Connectors:**
  - Two shielded red RJ45 jacks, IN and OUT, wired in parallel (ADR-0008).
  - Pluggable terminal blocks:
    - pressure (P+, P−);
    - 2 × pulse (F+, SIG, GND);
    - 2 × EC (+5V, OUT, GND);
    - 2 × thermistor (T+, T−);
    - 2 × load cell (E+, E−, A+, A−, shield), wired to the HX711 boards;
    - 1-Wire pigtail (+5V, DATA, GND) through a cable gland;
    - LCD (GND, +5V, SDA, SCL);
    - 2 × button.
  - Terminal-block series, pitch and catalog numbers are chosen at PCB layout.

## Alternatives rejected
- **Bare WROOM-1 module on the carrier:** the owner prefers a socketed, replaceable DevKitC with on-board USB.
- **Bare GPIO 1-Wire with a resistor pull-up:** there is no spare GPIO after the exclusions; DATA would not tolerate a 5 V miswire; there is no active pull-up for long lines.
- **Second 3.3 V regulator on the carrier:** it would parallel the DevKitC's SGM2212 or split the 3.3 V domain, with back-powering through I/O.
- **Isolated RS485:** ADR-0008 runs GND on the trunk; the isolated footprint remains an option.
- **Opto-coupled pulse inputs:** isolation buys nothing when the meter is powered and grounded by the node. Opto CTR spread complicates one universal 5-24 V input.
- **A single divider for 5 V and 24 V without a clamp:** no ratio puts both ends inside the LVC2G17 window and below its 5.5 V input limit.
- **Using UART0 (GPIO43/44) for RS485:** it conflicts with the DevKitC console and flashing bridge.
- **A carrier status LED:** it costs the last spare pin; the DevKitC's RGB LED does the job.
- **A trunk-voltage monitor on ADC1:** no pin left except the spare. Measure trunk voltage in Stage D.

## Open owner facts and bench checks
- **Owner facts:**
  - flow-meter output type, voltage, supply voltage and current (sets JP_OC and JP_SUPPLY, and replaces the 2 × 25 mA allowance);
  - EC module output range and supply current (keep the 0.5 divider only if the output is ≤ 5.5 V);
  - thermistor nominal resistance (sets Rref);
  - load-cell bridge resistance;
  - LCD module and backpack (current, pull-ups);
  - 1-Wire connector cavity numbering and ratings;
  - enclosure model.
- **Bench (Stage D):**
  - idle-bus bias at the controller, and the A/B polarity;
  - trunk voltage drop and per-node current against this budget;
  - USB plus 5V-pin coexistence on the DevKitC;
  - SGM2212 temperature with the production firmware;
  - 1-Wire maximum length and device count;
  - I²C rise time with the LCD cable;
  - enclosure internal temperature against the 50 °C design ambient.
