# ADR-0007: Firmware runtime for both ESP32 boards

**Status:** Accepted (2026-11-25; proposed 2026-11-12). Resolves the "embedded firmware platform selection" item in `README.md` and Stage B/C of `docs/CLAUDE_IMPLEMENTATION_BRIEF.md`.

**Decision:** Use C++ on the Arduino-ESP32 core (>= 3.0, which is built on ESP-IDF) for both the sensor node and the main controller, built with PlatformIO and a single shared toolchain. Keep all decision logic (fault-priority engine, validity/freshness checks, snapshot assembly, diversion and production state machine, register codec) in a framework-independent C++ library with no Arduino or ESP-IDF includes, tested on the host with PlatformIO's `native` environment. Hardware access (UART, I2C, GPIO, pulse counting, flash) sits behind small interfaces with mock implementations for host tests. ESP-IDF APIs (FreeRTOS tasks, PCNT, task watchdog) are called directly from the Arduino core where needed. Native ESP-IDF stays available as a later migration if the Arduino layer proves limiting.

**Rationale:**
- The vendor documents and supports only Arduino for the Waveshare `ESP32-S3-ETH-8DI-8RO`; its pin map, TCA9554 relay expander and RS485 demo code are Arduino (`hardware/main-controller/reference/README.md`). No ESP-IDF or MicroPython instructions are published.
- One language and toolchain across both boards lets the shared logic library and register constants be used on both, and on the host.
- The Arduino core exposes ESP-IDF underneath, so hardware pulse counting (PCNT), FreeRTOS tasks and the task watchdog are available for the sensor node without a separate framework.
- Rules out: MicroPython, because garbage-collection pauses and slower execution do not suit timing-sensitive RS485 framing, pulse counting and a safety-supervising state machine (and README already says not to assume it on the industrial board); ESPHome, because validity/freshness gating, deterministic fault arbitration, the actuator state machine, and host-side unit testing of that logic do not fit its component model. ESPHome does provide a `modbus_server` component, so this rejection rests on the component model, not on missing Modbus server support; its fit to the protocol's requirements (19200 8E1, coherent snapshot reads, exception behavior) was not evaluated.

**Consequences:**
- Add a C++ generator to `ro_tools` (or equivalent) so register addresses, scales, enums and fault codes come from `protocol/register_map.yaml` for firmware as well as the existing Python codec. Firmware constants must never be hand-copied (AGENTS.md rule 2).
- Cross-check: the existing Python simulator and client must pass against the firmware's host-built codec using the shared YAML, including address-base, signed and 32-bit word-order tests.
- Firmware directories (`firmware/sensor_node/`, `firmware/main_controller/`) become PlatformIO projects sharing a `lib/` logic library; vendor demo code is reference only and must not ship (reference/README.md finding 1).
- Hardware-dependent items stay mock-backed until bench verified (AGENTS.md rule 5).
- Project code must keep relay init order safe: write the output register to all-off before enabling the pins as outputs, as the demo does (reference/README.md finding 3).
- Enable the task watchdog on both boards; a hung main controller must leave K1 de-energized.
- Loguru and `uv` apply to host tools only, not firmware.

**Amendment (2026-11-25, issue #12):**
- **Modbus RTU server:** a minimal in-repo implementation, not a library (owner choice, 2026-11-25). The sensor node needs functions 03 and 04 only. The FC16 status block and name table are deferred; adding them extends this server.
- **Native test framework:** pytest at the Modbus wire boundary. All node logic builds into a PC program with fake hardware (`firmware/sensor_node/`, env `native`); pytest builds it with `pio run` and exchanges RTU frames with it over a local TCP socket using the existing Python client. C++ unit tests are added only where the wire cannot reach a case; they would use Unity 2.6.1 under `pio test`, which is not yet used or verified here.
- **Pinned versions:** PlatformIO platform `platformio/native@1.2.1`, C++17 without exceptions or RTTI. Verified with PlatformIO Core 6.2.0 and g++ 16.2.0 (MinGW) on Windows; Core and the host compiler are not pinned.
- **Layout:** the generated register header is in `firmware/lib/ro_protocol/` (shared by both boards); sensor-node logic is in `firmware/sensor_node/lib/sensor_node/`; the PC program is in `firmware/sensor_node/src/host/`. The module names and directories depart from section 9 of the Modbus spec (`drivers/`, `services/`, `protocol/{modbus_server,register_codec}`): the code is in `ro_hal`, `ro_node`, `ro_modbus_rtu` and the generated `ro_registers`.
- **ESP32 platform still TBD (issue #17):** the official `espressif32@6.13.0` declares `framework-arduinoespressif32 ~3.20017.0`, which is Arduino-ESP32 2.0.17 and does not meet the >= 3.0 requirement above. The bring-up probe's use of it (`framework = espidf`) does not carry over. No replacement is named until it has been built.

**TBD (do not guess):** pinned Arduino-ESP32 and ESP32 PlatformIO platform versions; ADC library for the sensor node (ADS1115 or better); how to persist calibration with version + CRC (NVS versus a flash partition); whether to adopt ESP-IDF directly if the Arduino layer blocks a requirement.
