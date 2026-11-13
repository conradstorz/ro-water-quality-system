# Main controller reference: Waveshare ESP32-S3-ETH-8DI-8RO

Vendor documentation and files for the main controller board, gathered 2026-11-12.
The box label reads `ESP32-S3-ETH-8DI-8RO` (see `../box-label-ESP32-S3-ETH-8DI-8RO.jpg`):
the common-Ethernet (non-PoE), RS485 variant. Nothing else shipped in the box.

Everything here is vendor or community information. **None of it has been verified on
the bench.** Items marked *unverified* must be confirmed before wiring field devices
(see AGENTS.md rules 3 and 5).

## Sources

| Source | URL |
|---|---|
| Waveshare wiki (primary manual) | https://www.waveshare.com/wiki/ESP32-S3-ETH-8DI-8RO |
| Waveshare wiki, PoE variant | https://www.waveshare.com/wiki/ESP32-S3-POE-ETH-8DI-8RO |
| Waveshare wiki, CAN variant (`-C`) | https://www.waveshare.com/wiki/ESP32-S3-ETH-8DI-8RO-C |
| ESPHome community config | https://devices.esphome.io/devices/Waveshare-ESP32-S3-ETH-8DI-8RO |

## Files in this folder

| File | What it is |
|---|---|
| `waveshare-wiki-ESP32-S3-ETH-8DI-8RO.html` | Saved copy of the wiki page (text only; images are in `images/`) |
| `esphome-device-page.html` | Saved copy of the ESPHome device page, including its YAML config |
| `ESP32-S3-POE-ETH-8DI-8RO-Demo.zip` | Waveshare demo package: four Arduino examples, bundled libraries, factory test firmware `Firmware/ESP32-S3-POE-ETH-8DI-8RO.bin`. SHA-256 starts `15dc5f074ca22455`. Kept zipped. |
| `datasheets/Esp32-s3_datasheet_en.pdf` | ESP32-S3 chip datasheet |
| `datasheets/Esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf` | ESP32-S3-WROOM-1/1U module datasheet |
| `datasheets/Esp32-s3_technical_reference_manual_en.pdf` | ESP32-S3 technical reference manual (14.5 MB) |
| `images/ESP32-S3-ETH-8DI-8RO-details-inter.jpg`, `-inter-1.jpg` | Onboard resources and interface call-outs |
| `images/ESP32-S3-ETH-8DI-8RO-details-size-1.jpg` | Outline dimensions |
| `images/ESP32-S3-ETH-8DI-8RO-logic-EN1.jpg`, `-logic-1.png` | Vendor "implementation logic" block diagrams |
| `images/ESP32-S3-16MB-OPI-Parameters.png` | Arduino IDE board settings screenshot |
| other `images/*` | Product photos |

| `waveshare-wiki-Flash_Firmware_Flashing_and_Erasing.html` | Saved copy of Waveshare's flashing/erasing guide (text only) |
| `tools/flash_download_tool.zip` | Espressif Flash Download Tool for Windows (26 MB), from https://dl.espressif.com/public/flash_download_tool.zip. SHA-256 starts `c1fbf280aa04cd8f`. |
| `tools/SSCOM5.13.1_For_ESP32_S3_Relay_6CH.zip` | SSCOM Windows serial terminal as linked from the wiki. SHA-256 starts `6a5139c19050b432`. |
| `tools/CH34XSER_MAC.7z` | CH34x USB-serial driver for macOS as linked from the wiki. SHA-256 starts `c041275b27906b6b`. |

The `tools/` archives contain third-party executables, stored as downloaded and never
run or scanned here.

Not downloadable as files: the "ESP32_Arduino offline package" (a Google Drive folder,
https://drive.google.com/drive/folders/1Pcs_A4FKWvdSHnz9lEBYqOpr-noTMbIv) and nRF Connect
(a phone app). Waveshare publishes **no schematic** for this board on the wiki.

## Specifications (wiki)

| Item | Value |
|---|---|
| Module | ESP32-S3-WROOM-1U-N16R8 per ESPHome page (16 MB flash, 8 MB PSRAM); external antenna, SMA female |
| Supply | 7–36 V DC on screw terminal, or 5 V / 1 A on USB-C |
| Relays | 8 channels, 1NO + 1NC each, contact rating ≤10 A 250 V AC or ≤10 A 30 V DC, optocoupler isolated |
| Digital inputs | 8 channels, "bidirectional optocoupler isolation" |
| RS485 | Isolated, 120 Ω termination enabled by jumper cap, TX/RX indicator LEDs |
| Ethernet | W5500, 10/100 Mbps over SPI |
| Other | PCF85063ATL RTC with battery header, TF card slot, buzzer, WS2812 RGB LED, BOOT and RESET buttons, pin header |
| Enclosure | DIN-rail ABS, 90 × 175 mm |

## Pin map

From the wiki interface tables, cross-checked against the demo source headers
(`Arduino/examples/MAIN_ALL/*.h` in the zip). Both agree except where noted.

| Function | Pin | Notes |
|---|---|---|
| Relay CH1–CH8 | TCA9554PWR EXIO1–EXIO8 | I2C expander at address `0x20`; not direct GPIO |
| I2C bus | SCL GPIO41, SDA GPIO42 | Shared by expander and RTC (demo `I2C_Driver.h`) |
| RTC interrupt | GPIO40 | PCF85063ATL |
| Digital input DI1–DI8 | GPIO4–GPIO11 | Demo uses `INPUT_PULLUP`; ESPHome config marks inputs inverted (active low at the MCU) |
| RS485 | TX GPIO17, RX GPIO18 | UART1. No DE/RE pin is listed anywhere, which implies automatic direction control (*unverified*) |
| W5500 | INT GPIO12, MOSI GPIO13, MISO GPIO14, SCLK GPIO15, CS GPIO16 | Demo also defines RST GPIO39 (not in the wiki table) |
| TF card | CLK GPIO48, CMD/MOSI GPIO47, D0/MISO GPIO45 | CS, D1, D2 not connected |
| RGB LED | GPIO38 | WS2812 |
| Buzzer | GPIO46 | |
| BOOT button | GPIO0 | |

GPIO0, GPIO45 and GPIO46 are ESP32-S3 strapping pins (chip datasheet).

## Programming

- **Vendor-supported toolchain:** Arduino IDE only. Board package "esp32 by Espressif
  Systems" ≥ 3.0.0, board "ESP32S3 Dev Module". Enable "USB CDC On Boot" to get `Serial`
  output over the USB-C port. The wiki gives no ESP-IDF or MicroPython instructions; the
  runtime for this project is still an open decision.
- **Demo libraries:** ArduinoJson v6.21.4, PubSubClient v2.8.0, NTPClient v3.2.1 (bundled
  in the zip).
- **Download mode:** hold BOOT, press and release RESET, then release BOOT. If the serial
  port shows "waiting for download..." after flashing, press RESET.
- **Factory firmware restore:** flash `Firmware/ESP32-S3-POE-ETH-8DI-8RO.bin` at address
  `0x00` (zip `ReadMe.txt`).
- **Demos:** `MAIN_WIFI_AP`, `MAIN_WIFI_STA`, `MAIN_WIFI_MQTT`, `MAIN_ALL`. The MQTT demos
  target the Waveshare cloud, which the wiki says is no longer maintained.

## Safety-relevant findings

These bear directly on `docs/safety/SAFETY_REQUIREMENTS.md` and the "Verify" list in
`../HARDWARE_SPEC.md`.

1. **The demo firmware switches relays from unauthenticated remote sources.** The demo
   code toggles relays on commands from Bluetooth, a WiFi access point web page, RS485,
   and directly from the digital inputs (`Relay_Immediate_Default 1` in `WS_DIN.h`). The
   board presumably ships with this or the test firmware loaded (*unverified*). Do not
   connect any load to the relay terminals until project firmware has replaced it.
2. **The demo firmware transmits on RS485 as a bus master.** It sends Modbus-style relay
   frames at 9600 8N1 to an external "Modbus RTU Relay" (`Extension_Enable 1`). Do not
   connect the sensor node bus while vendor firmware is loaded.
3. **Relay state between power-up and firmware init is unknown.** The relays are driven
   through the TCA9554 expander, which powers up with all pins as inputs. What the relay
   drivers do with undriven inputs depends on the board circuit, and there is no
   schematic. Measure on the bench: relay state at power-on, during reset, in download
   mode, and with firmware crashed. The demo writes the output register to `0x00` before
   switching the pins to output mode; project firmware should keep that order.
4. **Relays also hang on the I2C bus.** An I2C fault leaves relays in their last commanded
   state. This reinforces the existing rule that pump enable must pass through
   independent hardwired safety contacts.
5. **Relay rating is a resistive contact rating.** The wiki's own safety notes warn about
   inductive inrush and recommend fusing and RC snubbers or varistors, consistent with
   the spec's "no direct 120 VAC motor switching via board relay".

## Still open

- Digital input voltage range and thresholds, wet/dry contact wiring (wiki gives none).
- RS485 transceiver part, direction control, bias resistors.
- Whether USB-C and the 7–36 V input may be connected at the same time.
- Relay state at boot (item 3 above).
- Safety approvals: none stated.
- Schematic: not published; ask Waveshare support if needed.
