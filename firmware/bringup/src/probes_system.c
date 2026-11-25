/**
 * @file probes_system.c
 * @brief Read-only probes: build, clocks, chip, eFuse, strap latch, heap, partitions,
 *        temperature, brownout, USB.
 */
#include <inttypes.h>
#include <string.h>

#include "driver/temperature_sensor.h"
#include "driver/usb_serial_jtag.h"
#include "esp_app_desc.h"
#include "esp_chip_info.h"
#include "esp_efuse.h"
#include "esp_efuse_table.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "esp_idf_version.h"
#include "esp_mac.h"
#include "esp_partition.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "probes.h"
#include "sdkconfig.h"
#include "soc/gpio_reg.h"
#include "soc/rtc.h"
#include "soc/rtc_cntl_reg.h"
#include "soc/soc.h"

static const char *reset_reason_name(esp_reset_reason_t r)
{
    switch (r) {
    case ESP_RST_UNKNOWN: return "unknown";
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "ext";
    case ESP_RST_SW: return "sw";
    case ESP_RST_PANIC: return "panic";
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt";
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout";
    case ESP_RST_SDIO: return "sdio";
    case ESP_RST_USB: return "usb";
    case ESP_RST_JTAG: return "jtag";
    case ESP_RST_EFUSE: return "efuse";
    case ESP_RST_PWR_GLITCH: return "pwr_glitch";
    case ESP_RST_CPU_LOCKUP: return "cpu_lockup";
    default: return "other";
    }
}

void probe_build_and_clocks(void)
{
    const esp_app_desc_t *app = esp_app_get_description();
    PROBE("build.idf_version", "%s", esp_get_idf_version());
    PROBE("build.project", "%s", app->project_name);
    PROBE("build.app_version", "%s", app->version);
    PROBE("build.compile", "%s %s", app->date, app->time);
#ifdef BRINGUP_WIFI
    PROBE("build.env", "bringup_wifi");
#else
    PROBE("build.env", "bringup");
#endif
    PROBE("build.sdk_flash_mode", "%s", CONFIG_ESPTOOLPY_FLASHMODE);
    PROBE("build.sdk_flash_freq", "%s", CONFIG_ESPTOOLPY_FLASHFREQ);
    PROBE("build.sdk_flash_size", "%s", CONFIG_ESPTOOLPY_FLASHSIZE);

    esp_reset_reason_t rr = esp_reset_reason();
    PROBE("reset.reason", "%d:%s", (int)rr, reset_reason_name(rr));

    rtc_cpu_freq_config_t cpu;
    rtc_clk_cpu_freq_get_config(&cpu);
    PROBE("clock.cpu_mhz", "%" PRIu32, cpu.freq_mhz);
    PROBE("clock.cpu_source", "%d", (int)cpu.source);
    PROBE("clock.cpu_source_mhz", "%" PRIu32, cpu.source_freq_mhz);
    PROBE("clock.xtal_mhz", "%d", (int)rtc_clk_xtal_freq_get());
    PROBE("clock.rtc_slow_src", "%d", (int)rtc_clk_slow_src_get());
    PROBE("uptime.us", "%" PRId64, esp_timer_get_time());
}

/**
 * @brief Print one eFuse field (up to 32 bits) as decimal and hex.
 * @param name Field name for the key.
 * @param field ESP_EFUSE_* descriptor array.
 */
static void efuse_print(const char *name, const esp_efuse_desc_t *field[])
{
    int bits = esp_efuse_get_field_size(field);
    if (bits <= 0 || bits > 32) {
        printf("PROBE efuse.%s=bits:%d,not_read\n", name, bits);
        return;
    }
    uint32_t v = 0;
    esp_err_t err = esp_efuse_read_field_blob(field, &v, (size_t)bits);
    if (err != ESP_OK) {
        printf("PROBE efuse.%s=error:%s\n", name, esp_err_to_name(err));
        return;
    }
    printf("PROBE efuse.%s=%" PRIu32 ",hex:0x%" PRIx32 ",bits:%d\n", name, v, v, bits);
}

#define EF(n) efuse_print(#n, ESP_EFUSE_##n)

static void print_mac(const char *key, esp_mac_type_t type)
{
    uint8_t m[8] = {0};
    esp_err_t err = esp_read_mac(m, type);
    if (err != ESP_OK) {
        printf("PROBE mac.%s=error:%s\n", key, esp_err_to_name(err));
        return;
    }
    printf("PROBE mac.%s=%02x:%02x:%02x:%02x:%02x:%02x\n", key, m[0], m[1], m[2], m[3], m[4],
           m[5]);
}

void probe_chip_and_efuse(void)
{
    esp_chip_info_t ci;
    esp_chip_info(&ci);
    PROBE("chip.target", "%s", CONFIG_IDF_TARGET);
    PROBE("chip.model", "%d", (int)ci.model);
    PROBE("chip.revision", "v%d.%d", ci.revision / 100, ci.revision % 100);
    PROBE("chip.cores", "%d", ci.cores);
    PROBE("chip.features", "0x%08" PRIx32, ci.features);
    PROBE("chip.feature_emb_flash", "%d", (ci.features & CHIP_FEATURE_EMB_FLASH) ? 1 : 0);
    PROBE("chip.feature_wifi_bgn", "%d", (ci.features & CHIP_FEATURE_WIFI_BGN) ? 1 : 0);
    PROBE("chip.feature_ble", "%d", (ci.features & CHIP_FEATURE_BLE) ? 1 : 0);
    PROBE("chip.feature_bt", "%d", (ci.features & CHIP_FEATURE_BT) ? 1 : 0);
    PROBE("chip.feature_emb_psram", "%d", (ci.features & CHIP_FEATURE_EMB_PSRAM) ? 1 : 0);

    print_mac("base", ESP_MAC_BASE);
    print_mac("factory", ESP_MAC_EFUSE_FACTORY);
    print_mac("wifi_sta", ESP_MAC_WIFI_STA);
    print_mac("wifi_softap", ESP_MAC_WIFI_SOFTAP);
    print_mac("bt", ESP_MAC_BT);
    print_mac("custom", ESP_MAC_EFUSE_CUSTOM);

    PROBE("efuse.coding_check", "%s", esp_efuse_check_errors() == ESP_OK ? "ok" : "error");

    /* Chip, package and wafer */
    EF(PKG_VERSION);
    EF(WAFER_VERSION_MAJOR);
    EF(WAFER_VERSION_MINOR_HI);
    EF(WAFER_VERSION_MINOR_LO);
    EF(BLK_VERSION_MAJOR);
    EF(BLK_VERSION_MINOR);
    EF(DISABLE_WAFER_VERSION_MAJOR);
    EF(DISABLE_BLK_VERSION_MAJOR);
    /* Embedded flash and PSRAM */
    EF(FLASH_CAP);
    EF(FLASH_TEMP);
    EF(FLASH_VENDOR);
    EF(FLASH_TYPE);
    EF(FLASH_PAGE_SIZE);
    EF(FLASH_ECC_EN);
    EF(FLASH_ECC_MODE);
    EF(FLASH_TPUW);
    EF(PSRAM_CAP);
    EF(PSRAM_TEMP);
    EF(PSRAM_VENDOR);
    /* Flash supply voltage (VDD_SPI) */
    EF(VDD_SPI_FORCE);
    EF(VDD_SPI_TIEH);
    EF(VDD_SPI_XPD);
    /* Security */
    EF(SECURE_BOOT_EN);
    EF(SECURE_BOOT_AGGRESSIVE_REVOKE);
    EF(SECURE_VERSION);
    EF(SPI_BOOT_CRYPT_CNT);
    EF(DIS_DOWNLOAD_MANUAL_ENCRYPT);
    EF(DIS_DOWNLOAD_MODE);
    EF(DIS_FORCE_DOWNLOAD);
    EF(DIS_DIRECT_BOOT);
    EF(DIS_LEGACY_SPI_BOOT);
    EF(ENABLE_SECURITY_DOWNLOAD);
    EF(DIS_DOWNLOAD_ICACHE);
    EF(DIS_DOWNLOAD_DCACHE);
    EF(KEY_PURPOSE_0);
    EF(KEY_PURPOSE_1);
    EF(KEY_PURPOSE_2);
    EF(KEY_PURPOSE_3);
    EF(KEY_PURPOSE_4);
    EF(KEY_PURPOSE_5);
    /* JTAG and USB */
    EF(SOFT_DIS_JTAG);
    EF(HARD_DIS_JTAG);
    EF(DIS_PAD_JTAG);
    EF(DIS_USB_JTAG);
    EF(STRAP_JTAG_SEL);
    EF(DIS_USB_OTG);
    EF(DIS_USB_SERIAL_JTAG);
    EF(DIS_USB_SERIAL_JTAG_ROM_PRINT);
    EF(DIS_USB_SERIAL_JTAG_DOWNLOAD_MODE);
    EF(DIS_USB_OTG_DOWNLOAD_MODE);
    EF(USB_EXCHG_PINS);
    EF(USB_EXT_PHY_ENABLE);
    EF(UART_PRINT_CONTROL);
    /* Misc */
    EF(DIS_APP_CPU);
    EF(DIS_TWAI);
    EF(DIS_ICACHE);
    EF(DIS_DCACHE);

    uint8_t uid[16] = {0};
    if (esp_efuse_read_field_blob(ESP_EFUSE_OPTIONAL_UNIQUE_ID, uid, 128) == ESP_OK) {
        printf("PROBE efuse.OPTIONAL_UNIQUE_ID=");
        for (int i = 0; i < 16; i++) {
            printf("%02x", uid[i]);
        }
        printf("\n");
    }
}

void probe_strap_latch(void)
{
    /* S3 TRM v1.2 Register 6.15 GPIO_STRAP_REG: "bit5 ~ bit2 correspond to strapping
     * pins GPIO3, GPIO45, GPIO0, and GPIO46 respectively." */
    uint32_t raw = REG_READ(GPIO_STRAP_REG);
    PROBE("strap.raw", "0x%04" PRIx32, raw & 0xFFFF);
    PROBE("strap.gpio3", "%d", (int)((raw >> 5) & 1));
    PROBE("strap.gpio45", "%d", (int)((raw >> 4) & 1));
    PROBE("strap.gpio0", "%d", (int)((raw >> 3) & 1));
    PROBE("strap.gpio46", "%d", (int)((raw >> 2) & 1));
}

static void heap_line(const char *name, uint32_t caps)
{
    printf("PROBE heap.%s=total:%u,free:%u,largest:%u,min_free:%u\n", name,
           (unsigned)heap_caps_get_total_size(caps), (unsigned)heap_caps_get_free_size(caps),
           (unsigned)heap_caps_get_largest_free_block(caps),
           (unsigned)heap_caps_get_minimum_free_size(caps));
}

void probe_heap_and_partitions(void)
{
    heap_line("internal", MALLOC_CAP_INTERNAL);
    heap_line("dma", MALLOC_CAP_DMA);
    heap_line("spiram", MALLOC_CAP_SPIRAM);
    heap_line("default", MALLOC_CAP_DEFAULT);

    const esp_partition_t *running = esp_ota_get_running_partition();
    PROBE("partition.running", "%s", running ? running->label : "none");
    esp_partition_iterator_t it =
        esp_partition_find(ESP_PARTITION_TYPE_ANY, ESP_PARTITION_SUBTYPE_ANY, NULL);
    int n = 0;
    for (; it != NULL; it = esp_partition_next(it)) {
        const esp_partition_t *p = esp_partition_get(it);
        printf("PROBE partition.%s=type:%d,subtype:0x%02x,offset:0x%06" PRIx32
               ",size:0x%06" PRIx32 ",encrypted:%d\n",
               p->label, (int)p->type, (unsigned)p->subtype, p->address, p->size,
               p->encrypted ? 1 : 0);
        n++;
    }
    esp_partition_iterator_release(it);
    PROBE("partition.count", "%d", n);
}

void probe_temperature(void)
{
    temperature_sensor_handle_t h = NULL;
    temperature_sensor_config_t cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(-10, 80);
    esp_err_t err = temperature_sensor_install(&cfg, &h);
    if (err != ESP_OK) {
        PROBE("temp.internal_c", "error:%s", esp_err_to_name(err));
        return;
    }
    float c = 0;
    err = temperature_sensor_enable(h);
    if (err == ESP_OK) {
        err = temperature_sensor_get_celsius(h, &c);
        temperature_sensor_disable(h);
    }
    temperature_sensor_uninstall(h);
    if (err != ESP_OK) {
        PROBE("temp.internal_c", "error:%s", esp_err_to_name(err));
    } else {
        PROBE("temp.internal_c", "%.1f", c);
    }
}

void probe_brownout(void)
{
#ifdef CONFIG_ESP_BROWNOUT_DET
    PROBE("brownout.enabled", "1");
    PROBE("brownout.config_level", "%d", CONFIG_ESP_BROWNOUT_DET_LVL);
#else
    PROBE("brownout.enabled", "0");
#endif
    PROBE("brownout.reg_raw", "0x%08" PRIx32, REG_READ(RTC_CNTL_BROWN_OUT_REG));
}

void probe_usb(void)
{
#ifdef CONFIG_ESP_CONSOLE_SECONDARY_USB_SERIAL_JTAG
    PROBE("usb.secondary_console", "usb_serial_jtag");
#else
    PROBE("usb.secondary_console", "none");
#endif
    /* Connected = SOF packets seen from a host on the native "USB" port. */
    PROBE("usb.serial_jtag_sof_seen", "%d", usb_serial_jtag_is_connected() ? 1 : 0);
}
