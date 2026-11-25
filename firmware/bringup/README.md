# Sensor-node board bring-up probe

A bench-only firmware for the owner's generic ESP32-S3 N16R8 board (silkscreen "ESP32-S3 2025-V1.4", ADR-0012 section 1). It records as many board facts as firmware can see. Each fact is printed as one machine-parseable line:

```
PROBE <section>.<key>=<value>
```

Values are raw evidence (register values, counts, levels), never conclusions. The host tool `ro-tools bringup` saves the raw log and a JSON file of the key/values.

**This is not the sensor-node runtime.** It is pure ESP-IDF 5.5 (PlatformIO `framework = espidf`, platform `espressif32@6.13.0`, framework-espidf 5.5.3) because it is a throwaway bench tool that needs register-level access (strap latch, eFuse, RTC clock calibration). ADR-0007 (Arduino-ESP32 for the node runtime) is unaffected. Nothing here is a template for the node firmware.

## Safety preconditions

- **Board out of the carrier**, with nothing on its headers. The boot report applies pulls to header pins, and the opt-in `drive`/`sweep` commands drive them.
- **COM port only**: connect only the USB-C port labelled "COM" (CH343 bridge). The native "USB" port may also be connected to see whether it enumerates (VID 303A). No 24 V trunk, no 5Vin.
- **Factory image backed up.** The owner's full 16 MB dump exists (`esp32-s3-n16r8-v1.4-factory-full-16MB.bin`, SHA-256 `cd0f30ac…273e`, kept in `Documents/esp32-flash-backups/`, ADR-0012 bench note). Erasing destroys the factory image; restore it from that file if ever needed.
- **No eFuse is ever written.** The probe and the host tool only read eFuses. `ro-tools bringup --pre-erase` runs only allowlisted read commands (`bringup_capture.ESPTOOL_ALLOWED` / `ESPEFUSE_ALLOWED`); write, erase, burn and RAM-load commands are refused in code and by tests.
- The Wi-Fi env scans **passively** (receive only, no probe requests).

### Pin policy

`src/pin_policy.c` is the only file that configures GPIOs (a host test checks this). A request outside the policy prints `PROBE policy.violation=...` and aborts.

| Pins | Policy |
|---|---|
| 22-37 | never configured (in-package flash/PSRAM; touching them crashes the chip) |
| 19, 20 | never configured (USB D-/D+) |
| 43, 44 | never configured (UART0 console) |
| 0, 3, 45, 46 | straps: read-only. GPIO0 (BOOT) is read with its reset-default pull-up; 3, 45, 46 are only read from the strap latch |
| 48 | RGB LED via RMT only |
| 1, 2, 4-18, 21, 38-42, 47 | candidates: input scan at boot; drivable only after `arm` + `arm YES` (39-42 are the JTAG pins) |

Default boot drives no header pin. The only output is the RGB LED on GPIO48.

## Build

```
cd firmware/bringup
pio run -e bringup          # default: no Wi-Fi/BT linked
pio run -e bringup_wifi     # adds the passive Wi-Fi scan
```

Build settings that differ from the stock `esp32-s3-devkitc-1` board file: 16 MB flash, custom partition table (`partitions_bringup.csv`, 4 MB factory app), octal PSRAM with `CONFIG_SPIRAM_IGNORE_NOTFOUND=y` (a wrong guess reports `psram.initialized=0` instead of aborting).

**Flash mode is DIO, not QIO.** The flash reports manufacturer ID 0x1C (esptool bench result, ADR-0012). ESP-IDF 5.5.3's QIO-enable table (`bootloader_support/bootloader_flash/src/flash_qio_mode.c`) has no 0x1C entry. With QIO the bootloader would fall back to its generic procedure and write the status register of an unknown part. DIO needs no status-register write and is what the factory image used. The probe still reports the flash JEDEC ID, its image header mode and read throughput.

Default env and Wi-Fi: component requirements in ESP-IDF cannot depend on build flags, so `src/CMakeLists.txt` lists `esp_wifi` for both envs and the Wi-Fi code is compiled only with `-DBRINGUP_WIFI=1`. The Wi-Fi libraries stay on the link line, but the linker pulls no object from them. Check that with the symbol table (a plain grep of the map file also matches LOAD lines, ROM symbol addresses and linker-script patterns, which every S3 build has):

```
~/.platformio/packages/toolchain-xtensa-esp-elf/bin/xtensa-esp32s3-elf-nm .pio/build/bringup/firmware.elf | grep -c -E " [TtDdBb] (esp_wifi_|ieee80211|ppTask|wpa_|coex_)"
```

Expected: 0 for `bringup`, and many for `bringup_wifi`.

## Flash

Only after the safety preconditions above. Optional first: the read-only esptool/espefuse capture while the factory firmware is still on the board.

```
cd host_tools
uv run ro-tools bringup --port COM5 --pre-erase      # read-only esptool/espefuse; saves logs/bringup-preerase-<ts>.log
esptool --chip esp32s3 --port COM5 erase-flash      # destroys the factory image (backed up)
cd ../firmware/bringup
pio run -e bringup -t upload --upload-port COM5
```

## Capture

```
cd host_tools
uv run ro-tools bringup --port COM5
```

This opens the COM port with DTR and RTS released, resets the board into the app through the CH343 auto-reset lines (RTS, with IO0 left high), reads until `PROBE report.end` (default timeout 120 s), and writes `logs/bringup-<timestamp>.log` (raw) and `logs/bringup-<timestamp>.json` (`facts`: last value per key; `repeated`: every value of keys seen more than once, such as button events). `--no-reset` sends `report` instead of resetting. Exit status 0 = complete report, 1 = partial, 2 = serial error.

For the interactive commands use any terminal at 115200 on the COM port (`pio device monitor -b 115200`). Output also appears on the native "USB" port (USB-Serial-JTAG secondary console, output only).

## Console commands

| Command | Effect |
|---|---|
| `help` | list commands |
| `report` | rerun every read-only probe |
| `walk` | header walk: pull-ups on all candidates; prints `walk.event=gpio:<n>,level:<0/1>` for each change. Ground **only the candidate pins** (1, 2, 4-18, 21, 38-42, 47) in turn through a 1 kΩ resistor to confirm silkscreen-to-GPIO mapping. Any key exits (see below) |
| `arm` | prints "Board must be OUT of the carrier with nothing on the headers. Type: arm YES" |
| `arm YES` | arms active probes (only right after `arm`) |
| `drive <gpio>` | armed only, drivable pins only: high 2 s, low 2 s, back to input |
| `sweep` | armed only: `drive` each drivable pin in turn, printing `sweep.active=<gpio>`; watch the three discrete LEDs; any key stops between pins |
| `disarm` | disarm |

### Walk test: pins not to touch

| Header pin | Why not |
|---|---|
| RST | 1 kΩ against the EN pull-up resets the board and ends the walk |
| 35, 36, 37 | octal PSRAM lines: loading them can corrupt PSRAM or crash the chip |
| TX (43) | garbles the console while held |
| RX (44) | injects bytes, which the walk reads as a keypress and exits |
| 19, 20 | native USB D-/D+ |
| 3, 45, 46 | harmless, but never reported (straps are not configured) |
| 0 (BOOT) | reported as `boot_button.event`, not `walk.event` |

## What each probe answers

| Section (keys) | Evidence | ADR-0012 item |
|---|---|---|
| `build.*`, `reset.*`, `clock.*`, `uptime.*` | IDF version, reset reason, CPU MHz, crystal MHz (`rtc_clk_xtal_freq_get`) | confirms the 40 MHz crystal from esptool |
| `chip.*`, `mac.*` | model, revision, cores, feature bits, all MACs | chip identity (esptool: v0.2) |
| `efuse.*` | package, wafer, block version, flash/PSRAM capacity, vendor and temperature fields, VDD_SPI force/tieh, security, JTAG and USB disable fields | genuine N16R8 (closed by esptool; this adds raw eFuse fields), flash voltage 3.3 V |
| `strap.*` | GPIO_STRAP_REG latch; bits 5..2 = GPIO3, 45, 0, 46 (S3 TRM v1.2 Register 6.15) | strap levels as latched at reset |
| `flash.*` | JEDEC ID, physical and configured size, unique ID, bootloader header mode, 1 MB read throughput | 16 MB flash, 0x1C/0x7018 |
| `psram.*` | initialized, size, six-pattern test over all allocatable PSRAM (cache written back and invalidated between write and verify), MB/s | 8 MB octal PSRAM works at the configured speed |
| `heap.*`, `partition.*` | heap totals, partition table | build sanity |
| `temp.internal_c` | on-die temperature sensor | context for the readings |
| `brownout.*` | configured level and raw register | build sanity |
| `usb.*` | secondary console, USB-Serial-JTAG SOF seen | native "USB" port wiring (host side: VID 303A enumerates) |
| `pin.<n>` | pull-up read, pull-down read, verdict `floating` / `pulled_high` / `pulled_low` / `other` | anything on the board loading a header pin (e.g. a discrete LED or button) |
| `adc.gpio<n>` | ADC1 raw and mV, no pull, GPIO1-10 | same, analog view |
| `xtal32k.*` | 32 kHz oscillator start on GPIO15/16: XTAL cycles counted, measured Hz, tolerance check | "no 32.768 kHz crystal; GPIO15/16 free" |
| `boot_button.*` | GPIO0 initial level, debounced press/release events | "BOOT is GPIO0" |
| `rgb_led.*` | RMT init on GPIO48; the LED cycles red, green, blue, white, off at about 10 %, then a dim green heartbeat | RGB LED on GPIO48 (closed; visual re-check) |
| `wifi.*` (`bringup_wifi` only) | passive-scan AP count, RSSI, channel and BSSID of the strongest 8 APs (no SSIDs) | which antenna (PCB or IPEX) is active: compare runs with and without an IPEX antenna |
| `sweep.*`, `drive.*` (opt-in) | which GPIO was active while the owner watched the LEDs | what drives the three discrete LEDs |
| `walk.*` (opt-in) | which GPIO went low while a header pin was grounded | header silkscreen-to-GPIO mapping |

### Not covered (meter or scope; printed as `report.not_covered`)

Firmware cannot see these Stage D items:
- `sl_diode_5vin_path`: whether 5Vin passes through an SL diode.
- `sl_diode_orientation`: SL diode orientation (USB back-feed).
- `in_out_jumper`: the IN-OUT solder jumper state.
- `usb_otg_jumper`: the USB-OTG pad pair state.
- `ldo1117_dropout`: 1117 actual dropout.
- `ldo1117_temperature`: 1117 temperature.
- `3v3_oscillation`: 3V3 rail oscillation (scope).
- `usb_trunk_coexistence`: USB plus trunk coexistence.
- `discrete_led_drivers_if_sweep_inconclusive`: what drives the discrete LEDs if the passive scan and `sweep` show no GPIO link (they may be on a supply rail or the CH343).

No measured value from this probe goes into ADR-0012 or `docs/TODO.md` until the owner runs it on the board.
