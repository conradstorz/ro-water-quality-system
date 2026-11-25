/**
 * @file pin_policy.c
 * @brief GPIO access policy: the only file in the probe that touches GPIO configuration.
 */
#include "pin_policy.h"

#include <stdio.h>
#include <stdlib.h>

#include "driver/gpio.h"
#include "driver/rtc_io.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

const int PP_CANDIDATES[] = {1,  2,  4,  5,  6,  7,  8,  9,  10, 11, 12, 13,
                             14, 15, 16, 17, 18, 21, 38, 39, 40, 41, 42, 47};
const size_t PP_CANDIDATE_COUNT = sizeof(PP_CANDIDATES) / sizeof(PP_CANDIDATES[0]);

/** Pins that must never be configured, read or driven by GPIO code. */
static const int s_never_touch[] = {19, 20, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
                                    32, 33, 34, 35, 36, 37, 43, 44};
/** Strapping pins: read-only (only GPIO0 is ever configured, as a plain input). */
static const int s_straps[] = {0, 3, 45, 46};

_Static_assert(sizeof(PP_CANDIDATES) / sizeof(PP_CANDIDATES[0]) == 24,
               "candidate list changed: review ADR-0012 excluded-pin table");
_Static_assert(PP_RGB_LED_GPIO == 48, "RGB LED is GPIO48 (ADR-0012)");
_Static_assert(PP_BOOT_GPIO == 0, "BOOT is GPIO0");

static volatile bool s_armed = false;

/**
 * @brief Print a violation line and abort.
 * @param what Requested operation.
 * @param gpio GPIO number.
 */
static void violation(const char *what, int gpio)
{
    printf("PROBE policy.violation=op:%s,gpio:%d\n", what, gpio);
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(50));
    abort();
}

static bool in_list(const int *list, size_t n, int gpio)
{
    for (size_t i = 0; i < n; i++) {
        if (list[i] == gpio) {
            return true;
        }
    }
    return false;
}

bool pp_is_candidate(int gpio)
{
    return in_list(PP_CANDIDATES, PP_CANDIDATE_COUNT, gpio);
}

bool pp_is_drivable(int gpio)
{
    if (in_list(s_never_touch, sizeof(s_never_touch) / sizeof(s_never_touch[0]), gpio) ||
        in_list(s_straps, sizeof(s_straps) / sizeof(s_straps[0]), gpio) ||
        gpio == PP_RGB_LED_GPIO) {
        return false;
    }
    return pp_is_candidate(gpio);
}

void pp_self_test(void)
{
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        int g = PP_CANDIDATES[i];
        if (in_list(s_never_touch, sizeof(s_never_touch) / sizeof(s_never_touch[0]), g) ||
            in_list(s_straps, sizeof(s_straps) / sizeof(s_straps[0]), g) || g == PP_RGB_LED_GPIO ||
            !GPIO_IS_VALID_OUTPUT_GPIO(g)) {
            violation("self_test", g);
        }
    }
    printf("PROBE policy.self_test=ok\n");
}

void pp_arm(void)
{
    s_armed = true;
}

void pp_disarm(void)
{
    s_armed = false;
}

bool pp_is_armed(void)
{
    return s_armed;
}

void pp_config_input(int gpio, pp_pull_t pull)
{
    bool boot = (gpio == PP_BOOT_GPIO);
    if (!boot && !pp_is_candidate(gpio)) {
        violation("config_input", gpio);
    }
    /* GPIO0 keeps its reset-default internal pull-up (S3 TRM Table 8-1); a pull-down
     * on the strap/BOOT pin is refused. */
    if (boot && pull != PP_PULL_UP) {
        violation("config_input_strap_pull", gpio);
    }
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << gpio,
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = (pull == PP_PULL_UP) ? GPIO_PULLUP_ENABLE : GPIO_PULLUP_DISABLE,
        .pull_down_en = (pull == PP_PULL_DOWN) ? GPIO_PULLDOWN_ENABLE : GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
}

int pp_read(int gpio)
{
    if (gpio != PP_BOOT_GPIO && !pp_is_candidate(gpio)) {
        violation("read", gpio);
    }
    return gpio_get_level((gpio_num_t)gpio);
}

void pp_drive(int gpio, int level)
{
    if (!pp_is_drivable(gpio)) {
        violation("drive_not_drivable", gpio);
    }
    if (!s_armed) {
        violation("drive_not_armed", gpio);
    }
    ESP_ERROR_CHECK(gpio_set_level((gpio_num_t)gpio, level ? 1 : 0));
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << gpio,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));
    ESP_ERROR_CHECK(gpio_set_level((gpio_num_t)gpio, level ? 1 : 0));
}

void pp_release(int gpio)
{
    if (!pp_is_candidate(gpio)) {
        violation("release", gpio);
    }
    if (rtc_gpio_is_valid_gpio((gpio_num_t)gpio)) {
        rtc_gpio_deinit((gpio_num_t)gpio);
    }
    /* gpio_config selects the GPIO function and sets exactly no pull (gpio_reset_pin
     * would leave the pull-up enabled). */
    pp_config_input(gpio, PP_PULL_NONE);
}

void pp_release_all(void)
{
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        pp_release(PP_CANDIDATES[i]);
    }
}

void pp_require_rmt_led(int gpio)
{
    if (gpio != PP_RGB_LED_GPIO) {
        violation("rmt_led", gpio);
    }
}

void pp_require_xtal32k(int gpio)
{
    if (gpio != 15 && gpio != 16) {
        violation("xtal32k", gpio);
    }
}
