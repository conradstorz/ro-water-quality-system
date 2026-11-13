# ADR-0007: Firmware runtime for both ESP32 boards

**Status:** Proposed (2026-11-12) — pending owner review. Resolves the "embedded firmware platform selection" item in `README.md` and Stage B/C of `docs/CLAUDE_IMPLEMENTATION_BRIEF.md`.

**Decision:** Use C++ on the Arduino-ESP32 core (>= 3.0, which is built on ESP-IDF) for both the sensor node and the main controller, built with PlatformIO and a single shared toolchain. Keep all decision logic (fault-priority engine, validity/freshness checks, snapshot assembly, diversion and production state machine, register codec) in a framework-independent C++ library with no Arduino or ESP-IDF includes, tested on the host with PlatformIO's `native` environment. Hardware access (UART, I2C, GPIO, pulse counting, flash) sits behind small interfaces with mock implementations for host tests. ESP-IDF APIs (FreeRTOS tasks, PCNT, task watchdog) are called directly from the Arduino core where needed. Native ESP-IDF stays available as a later migration if the Arduino layer proves limiting.

**Rationale:**
- The vendor documents and supports only Arduino for the Waveshare `ESP32-S3-ETH-8DI-8RO`; its pin map, TCA9554 relay expander and RS485 demo code are Arduino (`hardware/main-controller/reference/README.md`). No ESP-IDF or MicroPython instructions are published.
- One language and toolchain across both boards lets the shared logic library and register constants be used on both, and on the host.
- The Arduino core exposes ESP-IDF underneath, so hardware pulse counting (PCNT), FreeRTOS tasks and the task watchdog are available for the sensor node without a separate framework.
- Rules out: MicroPython, because garbage-collection pauses and slower execution do not suit timing-sensitive RS485 framing, pulse counting and a safety-supervising state machine (and README already says not to assume it on the industrial board); ESPHome, because validity/freshness gating, deterministic fault arbitration and the actuator state machine do not fit its component model, and it has no Modbus RTU server for the sensor node.

**Consequences:**
- Add a C++ generator to `ro_tools` (or equivalent) so register addresses, scales, enums and fault codes come from `protocol/register_map.yaml` for firmware as well as the existing Python codec. Firmware constants must never be hand-copied (AGENTS.md rule 2).
- Cross-check: the existing Python simulator and client must pass against the firmware's host-built codec using the shared YAML, including address-base, signed and 32-bit word-order tests.
- Firmware directories (`firmware/sensor_node/`, `firmware/main_controller/`) become PlatformIO projects sharing a `lib/` logic library; vendor demo code is reference only and must not ship (reference/README.md finding 1).
- Hardware-dependent items stay mock-backed until bench verified (AGENTS.md rule 5).
- Project code must keep relay init order safe: write the output register to all-off before enabling the pins as outputs, as the demo does (reference/README.md finding 3).
- Enable the task watchdog on both boards; a hung main controller must leave K1 de-energized.
- Loguru and `uv` apply to host tools only, not firmware.

**TBD (do not guess):** pinned Arduino-ESP32 and PlatformIO platform versions; Modbus RTU server library versus a minimal in-repo implementation (evaluate against 19200 8E1, exception responses, CRC, 3-second stale-data inhibit and FC16 status block); unit-test framework for the native environment; ADC library for the sensor node (ADS1115 or better); how to persist calibration with version + CRC (NVS versus a flash partition); whether to adopt ESP-IDF directly if the Arduino layer blocks a requirement.
