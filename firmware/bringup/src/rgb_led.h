/**
 * @file rgb_led.h
 * @brief WS2812-type RGB LED on GPIO48 via RMT (hand-rolled bytes encoder).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Create the RMT channel on GPIO48.
 * @return true on success (prints ``PROBE rgb_led.init=...`` either way).
 */
bool rgb_led_init(void);

/**
 * @brief Set the LED colour.
 * @param r Red 0-255.
 * @param g Green 0-255.
 * @param b Blue 0-255.
 */
void rgb_led_set(uint8_t r, uint8_t g, uint8_t b);

/** @brief Cycle R, G, B, white, off at about 10 % brightness (blocking, ~2.5 s). */
void rgb_led_boot_cycle(void);

/** @brief Start a slow, dim heartbeat task. */
void rgb_led_heartbeat_start(void);

#ifdef __cplusplus
}
#endif
