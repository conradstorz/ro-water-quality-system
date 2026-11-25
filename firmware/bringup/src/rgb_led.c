/**
 * @file rgb_led.c
 * @brief WS2812 driver: RMT TX channel + rmt_new_bytes_encoder, GRB order.
 *
 * Timing follows ESP-IDF's examples/peripherals/rmt/led_strip encoder (T0H 0.3 us,
 * T0L 0.9 us, T1H 0.9 us, T1L 0.3 us at 10 MHz). The reset/latch gap is produced by
 * waiting for the transmission to finish and idling the line low for >= 1 ms.
 */
#include "rgb_led.h"

#include "driver/rmt_encoder.h"
#include "driver/rmt_tx.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "pin_policy.h"
#include "probes.h"

#define LED_RES_HZ 10000000U
#define LED_LEVEL 25U /* ~10 % of 255 */
#define HEARTBEAT_LEVEL 6U

static rmt_channel_handle_t s_chan;
static rmt_encoder_handle_t s_enc;
static SemaphoreHandle_t s_lock;

bool rgb_led_init(void)
{
    pp_require_rmt_led(PP_RGB_LED_GPIO);
    rmt_tx_channel_config_t ccfg = {
        .gpio_num = PP_RGB_LED_GPIO,
        .clk_src = RMT_CLK_SRC_DEFAULT,
        .resolution_hz = LED_RES_HZ,
        .mem_block_symbols = 64,
        .trans_queue_depth = 2,
    };
    esp_err_t err = rmt_new_tx_channel(&ccfg, &s_chan);
    if (err == ESP_OK) {
        rmt_bytes_encoder_config_t ecfg = {
            .bit0 = {.level0 = 1, .duration0 = 3, .level1 = 0, .duration1 = 9},
            .bit1 = {.level0 = 1, .duration0 = 9, .level1 = 0, .duration1 = 3},
            .flags.msb_first = 1,
        };
        err = rmt_new_bytes_encoder(&ecfg, &s_enc);
    }
    if (err == ESP_OK) {
        err = rmt_enable(s_chan);
    }
    s_lock = xSemaphoreCreateMutex();
    PROBE("rgb_led.gpio", "%d", PP_RGB_LED_GPIO);
    PROBE("rgb_led.init", "%s", err == ESP_OK ? "ok" : esp_err_to_name(err));
    if (err != ESP_OK) {
        s_chan = NULL;
    }
    return err == ESP_OK;
}

void rgb_led_set(uint8_t r, uint8_t g, uint8_t b)
{
    if (s_chan == NULL) {
        return;
    }
    uint8_t grb[3] = {g, r, b};
    rmt_transmit_config_t tcfg = {.loop_count = 0};
    xSemaphoreTake(s_lock, portMAX_DELAY);
    if (rmt_transmit(s_chan, s_enc, grb, sizeof(grb), &tcfg) == ESP_OK) {
        rmt_tx_wait_all_done(s_chan, pdMS_TO_TICKS(100));
    }
    vTaskDelay(pdMS_TO_TICKS(2)); /* latch: line idles low > 50 us */
    xSemaphoreGive(s_lock);
}

void rgb_led_boot_cycle(void)
{
    static const struct {
        const char *name;
        uint8_t r, g, b;
    } steps[] = {
        {"red", LED_LEVEL, 0, 0},
        {"green", 0, LED_LEVEL, 0},
        {"blue", 0, 0, LED_LEVEL},
        {"white", LED_LEVEL, LED_LEVEL, LED_LEVEL},
        {"off", 0, 0, 0},
    };
    for (size_t i = 0; i < sizeof(steps) / sizeof(steps[0]); i++) {
        PROBE("rgb_led.cycle", "%s", steps[i].name);
        rgb_led_set(steps[i].r, steps[i].g, steps[i].b);
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

static void heartbeat_task(void *arg)
{
    (void)arg;
    for (;;) {
        rgb_led_set(0, HEARTBEAT_LEVEL, 0);
        vTaskDelay(pdMS_TO_TICKS(80));
        rgb_led_set(0, 0, 0);
        vTaskDelay(pdMS_TO_TICKS(1920));
    }
}

void rgb_led_heartbeat_start(void)
{
    if (s_chan != NULL) {
        xTaskCreate(heartbeat_task, "led_hb", 2560, NULL, 2, NULL);
    }
}
