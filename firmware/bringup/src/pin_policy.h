/**
 * @file pin_policy.h
 * @brief The only module allowed to configure or drive GPIOs in the bring-up probe.
 *
 * Every gpio_config / gpio_set_direction / gpio_set_pull_mode / gpio_set_level call
 * lives in pin_policy.c. Any request outside the policy prints a
 * ``PROBE policy.violation=...`` line and aborts.
 *
 * Classes (ADR-0012 section 1, WROOM-1 DS Table 3/4, S3 DS Table 2-14):
 * - never touched: 22-37 (flash/PSRAM; touching them crashes the chip);
 * - read-only: 0, 3, 45, 46 (straps; GPIO0 is the BOOT button);
 * - never touched by this module: 19, 20 (USB), 43, 44 (UART0 console);
 * - RMT LED only: 48;
 * - input candidates: 1, 2, 4-18, 21, 38-42, 47;
 * - drivable (opt-in, armed only): the same candidates (39-42 are JTAG pins).
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/** GPIO of the on-board WS2812 RGB LED (ADR-0012 bench note). */
#define PP_RGB_LED_GPIO 48
/** GPIO of the BOOT button (assumed as on the DevKitC; the probe reports it). */
#define PP_BOOT_GPIO 0

/** Pull selection for input configuration. */
typedef enum {
    PP_PULL_NONE = 0,
    PP_PULL_UP,
    PP_PULL_DOWN,
} pp_pull_t;

/** Header candidate pins (input-scannable, drivable only when armed). */
extern const int PP_CANDIDATES[];
/** Number of entries in ::PP_CANDIDATES. */
extern const size_t PP_CANDIDATE_COUNT;

/**
 * @brief Check the policy tables for overlaps; abort on inconsistency.
 *
 * Prints ``PROBE policy.self_test=ok`` on success.
 */
void pp_self_test(void);

/** @return true if @p gpio is a header candidate pin. */
bool pp_is_candidate(int gpio);
/** @return true if @p gpio may be driven as an output (candidate list only). */
bool pp_is_drivable(int gpio);

/** @brief Arm active output probes (owner confirmed board out of carrier). */
void pp_arm(void);
/** @brief Disarm active output probes. */
void pp_disarm(void);
/** @return true while armed. */
bool pp_is_armed(void);

/**
 * @brief Configure a candidate pin (or GPIO0) as an input with the given pull.
 *
 * Aborts if @p gpio is not a candidate and not ::PP_BOOT_GPIO, or if GPIO0 is
 * requested with anything but its reset-default pull-up.
 *
 * @param gpio GPIO number.
 * @param pull Pull selection.
 */
void pp_config_input(int gpio, pp_pull_t pull);

/**
 * @brief Read the level of a pin previously configured by pp_config_input().
 * @param gpio GPIO number (candidate or GPIO0).
 * @return 0 or 1.
 */
int pp_read(int gpio);

/**
 * @brief Drive a drivable pin as a push-pull output. Requires pp_arm().
 *
 * The level register is written before the output is enabled.
 *
 * @param gpio GPIO number.
 * @param level 0 or 1.
 */
void pp_drive(int gpio, int level);

/**
 * @brief Return a candidate pin to digital input, no pull (the probe's idle state).
 *
 * Also returns RTC/analog pads to the digital GPIO function.
 *
 * @param gpio GPIO number.
 */
void pp_release(int gpio);

/** @brief Release every candidate pin (pp_release on each). */
void pp_release_all(void);

/**
 * @brief Assert that @p gpio may be handed to the RMT peripheral for the RGB LED.
 * @param gpio GPIO number; only ::PP_RGB_LED_GPIO passes.
 */
void pp_require_rmt_led(int gpio);

/**
 * @brief Assert that @p gpio may be handed to the 32 kHz crystal oscillator pads.
 * @param gpio GPIO number; only 15 and 16 pass.
 */
void pp_require_xtal32k(int gpio);

#ifdef __cplusplus
}
#endif
