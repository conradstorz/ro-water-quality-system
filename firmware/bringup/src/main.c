/**
 * @file main.c
 * @brief Bench bring-up probe for the sensor-node ESP32-S3 N16R8 clone (ADR-0012).
 *
 * Boot: RGB LED cycle, BOOT-button monitor, one full read-only report.
 * Then a line console on UART0 (CH343 "COM" port, 115200). Output is mirrored to
 * the USB-Serial-JTAG "USB" port (secondary console, output only).
 *
 * Default boot drives no header pin. Active output probes (drive, sweep) need
 * ``arm`` then ``arm YES``.
 */
#include <ctype.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "driver/uart.h"
#include "esp_err.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "pin_policy.h"
#include "probes.h"
#include "rgb_led.h"

#define CONSOLE_UART UART_NUM_0
#define CONSOLE_LINE_MAX 64

/** Items firmware cannot see; owner measures them with a meter or scope (ADR-0012 Stage D). */
#define NOT_COVERED                                                                              \
    "sl_diode_5vin_path,sl_diode_orientation,in_out_jumper,usb_otg_jumper,ldo1117_dropout,"      \
    "ldo1117_temperature,3v3_oscillation,usb_trunk_coexistence,"                                 \
    "discrete_led_drivers_if_sweep_inconclusive"

static int s_report_no;
static bool s_arm_prompted;

static void run_report(void)
{
    s_report_no++;
    PROBE("report.begin", "%d", s_report_no);
    PROBE("report.format", "%d", PROBE_FORMAT_VERSION);
    probe_build_and_clocks();
    probe_chip_and_efuse();
    probe_strap_latch();
    probe_flash();
    probe_psram();
    probe_heap_and_partitions();
    probe_temperature();
    probe_brownout();
    probe_usb();
    probe_pin_scan();
    probe_adc_scan();
    probe_xtal32k();
#ifdef BRINGUP_WIFI
    probe_wifi_scan();
#endif
    pp_release_all();
    PROBE("report.armed", "%d", pp_is_armed() ? 1 : 0);
    PROBE("report.not_covered", "%s", NOT_COVERED);
    PROBE("report.end", "%d", s_report_no);
}

/**
 * @return true if a non-line-ending byte is waiting on the console (consumes
 *         bytes). CR and LF are skipped so the tail of the CRLF that ended the
 *         command line does not count as a stop request.
 */
static bool key_pressed(void)
{
    uint8_t c;
    while (uart_read_bytes(CONSOLE_UART, &c, 1, 0) > 0) {
        if (c != '\r' && c != '\n') {
            return true;
        }
    }
    return false;
}

/**
 * @brief Read one line from the console with echo and backspace handling.
 * @param buf Output buffer.
 * @param len Buffer size.
 */
static void read_line(char *buf, size_t len)
{
    size_t n = 0;
    printf("bringup> ");
    fflush(stdout);
    for (;;) {
        uint8_t c;
        if (uart_read_bytes(CONSOLE_UART, &c, 1, pdMS_TO_TICKS(100)) <= 0) {
            continue;
        }
        if (c == '\r' || c == '\n') {
            if (n == 0) {
                continue;
            }
            printf("\n");
            buf[n] = '\0';
            return;
        }
        if ((c == 0x08 || c == 0x7F) && n > 0) {
            n--;
            printf("\b \b");
        } else if (isprint(c) && n + 1 < len) {
            buf[n++] = (char)c;
            putchar(c);
        }
        fflush(stdout);
    }
}

static void cmd_help(void)
{
    printf("commands:\n"
           "  help          this text\n"
           "  report        rerun all read-only probes\n"
           "  walk          header walk: pull-ups on all candidates, print pins that go low;\n"
           "                ground ONLY pins 1,2,4-18,21,38-42,47 through 1k; any key exits.\n"
           "                Never touch RST, 35-37, TX, RX, 19, 20. BOOT/GPIO0 shows as\n"
           "                boot_button.event\n"
           "  arm           show the arming precondition\n"
           "  arm YES       arm active output probes\n"
           "  drive <gpio>  (armed) drive pin high 2 s, low 2 s, release\n"
           "  sweep         (armed) drive each drivable pin in turn; 'q' stops between pins\n"
           "  disarm        disarm active output probes\n");
}

static void cmd_drive(const char *arg)
{
    char *end = NULL;
    long g = strtol(arg, &end, 10);
    if (end == arg || *end != '\0') {
        PROBE("drive.refused", "bad_argument");
        return;
    }
    if (!pp_is_armed()) {
        PROBE("drive.refused", "gpio:%ld,not_armed", g);
        return;
    }
    if (!pp_is_drivable((int)g)) {
        PROBE("drive.refused", "gpio:%ld,not_drivable", g);
        return;
    }
    probe_drive_pin((int)g, "drive");
}

static void cmd_sweep(void)
{
    if (!pp_is_armed()) {
        PROBE("sweep.refused", "not_armed");
        return;
    }
    PROBE("sweep.begin", "1");
    for (size_t i = 0; i < PP_CANDIDATE_COUNT; i++) {
        int g = PP_CANDIDATES[i];
        if (!pp_is_drivable(g)) {
            continue;
        }
        if (key_pressed()) {
            PROBE("sweep.stopped_before", "%d", g);
            break;
        }
        PROBE("sweep.active", "%d", g);
        probe_drive_pin(g, "sweep");
    }
    pp_release_all();
    PROBE("sweep.end", "1");
}

static void handle(char *line)
{
    while (*line == ' ') {
        line++;
    }
    if (strcmp(line, "help") == 0) {
        cmd_help();
    } else if (strcmp(line, "report") == 0) {
        run_report();
    } else if (strcmp(line, "arm") == 0) {
        s_arm_prompted = true;
        printf("Board must be OUT of the carrier with nothing on the headers. Type: arm YES\n");
        PROBE("arm.state", "prompted");
    } else if (strcmp(line, "arm YES") == 0) {
        if (!s_arm_prompted) {
            PROBE("arm.refused", "type_arm_first");
            return;
        }
        s_arm_prompted = false;
        pp_arm();
        PROBE("arm.state", "armed");
    } else if (strcmp(line, "disarm") == 0) {
        s_arm_prompted = false;
        pp_disarm();
        PROBE("arm.state", "disarmed");
    } else if (strncmp(line, "drive ", 6) == 0) {
        cmd_drive(line + 6);
    } else if (strcmp(line, "sweep") == 0) {
        cmd_sweep();
    } else if (strcmp(line, "walk") == 0) {
        printf("walk: ground ONLY pins 1,2,4-18,21,38-42,47 through 1k (never RST, 35-37, TX, "
               "RX, 19, 20); press any key to stop\n");
        probe_walk(key_pressed);
    } else {
        PROBE("console.unknown", "%s", line);
    }
}

void app_main(void)
{
    ESP_ERROR_CHECK(uart_driver_install(CONSOLE_UART, 512, 0, 0, NULL, 0));
    PROBE("boot.banner", "ro-bringup-probe");
    pp_self_test();
    if (rgb_led_init()) {
        rgb_led_boot_cycle();
    }
    boot_button_start();
    run_report();
    rgb_led_heartbeat_start();
    cmd_help();
    char line[CONSOLE_LINE_MAX];
    for (;;) {
        read_line(line, sizeof(line));
        handle(line);
    }
}
