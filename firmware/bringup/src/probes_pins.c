/**
 * @file probes_pins.c
 * @brief Pin probes: 32 kHz crystal, passive pull scan, ADC1 scan, header walk,
 *        opt-in drive, BOOT button monitor. All GPIO configuration goes through pin_policy.
 */
#include <inttypes.h>
#include <string.h>

#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_err.h"
#include "esp_rom_sys.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pin_policy.h"
#include "probes.h"
#include "soc/rtc.h"
#include "soc/rtc_io_reg.h"
#include "soc/soc.h"

/* Non-static in esp_hw_support/port/esp32s3/rtc_time.c but not declared in the S3 rtc.h.
 * Returns the number of XTAL cycles counted over @p slowclk_cycles, 0 on timeout. */
extern uint32_t rtc_clk_cal_internal(rtc_cal_sel_t cal_clk, uint32_t slowclk_cycles);

#define SETTLE_MS 1
#define XTAL32K_STARTUP_MS 1000
#define XTAL32K_CAL_CYCLES 100

/* ------------------------------------------------------------ 32 kHz XTAL */

void probe_xtal32k(void)
{
    pp_require_xtal32k(15);
    pp_require_xtal32k(16);
    if (rtc_clk_32k_enabled()) {
        PROBE("xtal32k.result", "not_tested:already_enabled");
        return;
    }
    pp_release(15);
    pp_release(16);
    rtc_clk_32k_enable(true);
    vTaskDelay(pdMS_TO_TICKS(XTAL32K_STARTUP_MS));
    uint32_t xtal_cycles = rtc_clk_cal_internal(RTC_CAL_32K_XTAL, XTAL32K_CAL_CYCLES);
    uint32_t period = rtc_clk_cal(RTC_CAL_32K_XTAL, XTAL32K_CAL_CYCLES);
    rtc_clk_32k_enable(false);
    CLEAR_PERI_REG_MASK(RTC_IO_XTAL_32P_PAD_REG, RTC_IO_X32P_MUX_SEL);
    CLEAR_PERI_REG_MASK(RTC_IO_XTAL_32N_PAD_REG, RTC_IO_X32N_MUX_SEL);
    pp_release(15);
    pp_release(16);

    uint32_t xtal_mhz = (uint32_t)rtc_clk_xtal_freq_get();
    PROBE("xtal32k.startup_wait_ms", "%d", XTAL32K_STARTUP_MS);
    PROBE("xtal32k.cal_slow_cycles", "%d", XTAL32K_CAL_CYCLES);
    PROBE("xtal32k.cal_xtal_cycles", "%" PRIu32, xtal_cycles);
    double hz = xtal_cycles ? (double)xtal_mhz * 1e6 * XTAL32K_CAL_CYCLES / (double)xtal_cycles : 0.0;
    PROBE("xtal32k.measured_hz", "%.1f", hz);
    /* rtc_clk_cal returns 0 on timeout or when the count is outside +/-0.05 % of 32768 Hz. */
    PROBE("xtal32k.cal_period_q19", "%" PRIu32, period);
    PROBE("xtal32k.result", "%s",
          xtal_cycles == 0 ? "timeout" : (period != 0 ? "in_tolerance" : "out_of_tolerance"));
}

/* -------------------------------------------------------- passive pull scan */

void probe_pin_scan(void)
{
    PROBE("pinscan.settle_ms", "%d", SETTLE_MS);
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        int g = PP_CANDIDATES[i];
        pp_config_input(g, PP_PULL_UP);
        esp_rom_delay_us(SETTLE_MS * 1000);
        int pu = pp_read(g);
        pp_config_input(g, PP_PULL_DOWN);
        esp_rom_delay_us(SETTLE_MS * 1000);
        int pd = pp_read(g);
        pp_release(g);
        const char *verdict = "other";
        if (pu == 1 && pd == 0) {
            verdict = "floating";
        } else if (pu == 1 && pd == 1) {
            verdict = "pulled_high";
        } else if (pu == 0 && pd == 0) {
            verdict = "pulled_low";
        }
        printf("PROBE pin.%d=pu:%d,pd:%d,verdict:%s\n", g, pu, pd, verdict);
    }
}

/* ------------------------------------------------------------- ADC1 scan */

#define ADC_SAMPLES 8

void probe_adc_scan(void)
{
    adc_oneshot_unit_handle_t unit = NULL;
    adc_oneshot_unit_init_cfg_t ucfg = {.unit_id = ADC_UNIT_1};
    esp_err_t err = adc_oneshot_new_unit(&ucfg, &unit);
    if (err != ESP_OK) {
        PROBE("adc.unit1", "error:%s", esp_err_to_name(err));
        return;
    }
    adc_cali_handle_t cali = NULL;
    adc_cali_curve_fitting_config_t ccfg = {
        .unit_id = ADC_UNIT_1,
        .atten = ADC_ATTEN_DB_12,
        .bitwidth = ADC_BITWIDTH_DEFAULT,
    };
    esp_err_t cerr = adc_cali_create_scheme_curve_fitting(&ccfg, &cali);
    PROBE("adc.calibration", "%s", cerr == ESP_OK ? "curve_fitting" : esp_err_to_name(cerr));
    PROBE("adc.atten", "db_12");
    PROBE("adc.samples", "%d", ADC_SAMPLES);

    for (int g = 1; g <= 10; g++) {
        if (!pp_is_candidate(g)) {
            continue;
        }
        adc_unit_t u;
        adc_channel_t ch;
        if (adc_oneshot_io_to_channel(g, &u, &ch) != ESP_OK || u != ADC_UNIT_1) {
            printf("PROBE adc.gpio%d=not_adc1\n", g);
            continue;
        }
        pp_config_input(g, PP_PULL_NONE);
        adc_oneshot_chan_cfg_t chcfg = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_DEFAULT};
        err = adc_oneshot_config_channel(unit, ch, &chcfg);
        int sum = 0;
        int mn = 1 << 30;
        int mx = -1;
        for (int s = 0; s < ADC_SAMPLES && err == ESP_OK; s++) {
            int raw = 0;
            err = adc_oneshot_read(unit, ch, &raw);
            sum += raw;
            mn = raw < mn ? raw : mn;
            mx = raw > mx ? raw : mx;
        }
        if (err != ESP_OK) {
            printf("PROBE adc.gpio%d=error:%s\n", g, esp_err_to_name(err));
            continue;
        }
        int avg = sum / ADC_SAMPLES;
        int mv = -1;
        if (cali != NULL && adc_cali_raw_to_voltage(cali, avg, &mv) != ESP_OK) {
            mv = -1;
        }
        printf("PROBE adc.gpio%d=ch:%d,raw_avg:%d,raw_min:%d,raw_max:%d,mv:%d\n", g, (int)ch, avg,
               mn, mx, mv);
    }
    if (cali != NULL) {
        adc_cali_delete_scheme_curve_fitting(cali);
    }
    adc_oneshot_del_unit(unit);
    for (int g = 1; g <= 10; g++) {
        if (pp_is_candidate(g)) {
            pp_release(g);
        }
    }
}

/* ------------------------------------------------------------ header walk */

#define WALK_POLL_MS 5
#define WALK_DEBOUNCE_SAMPLES 4

void probe_walk(bool (*stop_requested)(void))
{
    int stable[PP_CANDIDATE_COUNT];
    int pending[PP_CANDIDATE_COUNT];
    int count[PP_CANDIDATE_COUNT];
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        pp_config_input(PP_CANDIDATES[i], PP_PULL_UP);
    }
    vTaskDelay(pdMS_TO_TICKS(10));
    printf("PROBE walk.start_low=");
    bool any = false;
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        stable[i] = pp_read(PP_CANDIDATES[i]);
        pending[i] = stable[i];
        count[i] = 0;
        if (stable[i] == 0) {
            printf("%s%d", any ? "," : "", PP_CANDIDATES[i]);
            any = true;
        }
    }
    printf("%s\n", any ? "" : "none");
    while (!stop_requested()) {
        for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
            int v = pp_read(PP_CANDIDATES[i]);
            if (v == stable[i]) {
                count[i] = 0;
                continue;
            }
            if (v != pending[i]) {
                pending[i] = v;
                count[i] = 0;
            }
            if (++count[i] >= WALK_DEBOUNCE_SAMPLES) {
                stable[i] = v;
                count[i] = 0;
                printf("PROBE walk.event=gpio:%d,level:%d\n", PP_CANDIDATES[i], v);
            }
        }
        vTaskDelay(pdMS_TO_TICKS(WALK_POLL_MS));
    }
    pp_release_all();
    PROBE("walk.end", "1");
}

/* ------------------------------------------------------------ opt-in drive */

void probe_drive_pin(int gpio, const char *section)
{
    printf("PROBE %s.pin=gpio:%d,level:1,hold_ms:2000\n", section, gpio);
    pp_drive(gpio, 1);
    vTaskDelay(pdMS_TO_TICKS(2000));
    printf("PROBE %s.pin=gpio:%d,level:0,hold_ms:2000\n", section, gpio);
    pp_drive(gpio, 0);
    vTaskDelay(pdMS_TO_TICKS(2000));
    pp_release(gpio);
    printf("PROBE %s.pin=gpio:%d,released\n", section, gpio);
}

/* ------------------------------------------------------------ BOOT button */

#define BTN_POLL_MS 5
#define BTN_DEBOUNCE_MS 20

static void boot_button_task(void *arg)
{
    (void)arg;
    pp_config_input(PP_BOOT_GPIO, PP_PULL_UP);
    vTaskDelay(pdMS_TO_TICKS(2));
    int stable = pp_read(PP_BOOT_GPIO);
    PROBE("boot_button.initial_level", "%d", stable);
    int elapsed = 0;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(BTN_POLL_MS));
        int v = pp_read(PP_BOOT_GPIO);
        if (v == stable) {
            elapsed = 0;
            continue;
        }
        elapsed += BTN_POLL_MS;
        if (elapsed >= BTN_DEBOUNCE_MS) {
            stable = v;
            elapsed = 0;
            PROBE("boot_button.event", "%s", v == 0 ? "press" : "release");
        }
    }
}

void boot_button_start(void)
{
    xTaskCreate(boot_button_task, "boot_btn", 3072, NULL, 3, NULL);
}
