/**
 * @file probes_memory.c
 * @brief Read-only flash probe and non-destructive (heap-only) PSRAM pattern test.
 */
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

#include "esp_cache.h"
#include "esp_err.h"
#include "esp_flash.h"
#include "esp_heap_caps.h"
#include "esp_ota_ops.h"
#include "esp_psram.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "probes.h"
#include "sdkconfig.h"
#include "spi_flash_chip_driver.h"

#define FLASH_READ_TEST_BYTES (1024U * 1024U)
#define FLASH_READ_CHUNK 4096U

void probe_flash(void)
{
    esp_flash_t *chip = esp_flash_default_chip;
    uint32_t id = 0;
    esp_err_t err = esp_flash_read_id(chip, &id);
    if (err == ESP_OK) {
        PROBE("flash.jedec_id", "0x%06" PRIx32, id);
        PROBE("flash.manufacturer_id", "0x%02" PRIx32, (id >> 16) & 0xFF);
        PROBE("flash.device_id", "0x%04" PRIx32, id & 0xFFFF);
    } else {
        PROBE("flash.jedec_id", "error:%s", esp_err_to_name(err));
    }
    if (chip != NULL && chip->chip_drv != NULL) {
        PROBE("flash.idf_chip_driver", "%s", chip->chip_drv->name);
        PROBE("flash.read_mode", "%d", (int)chip->read_mode);
    }

    uint32_t phys = 0;
    err = esp_flash_get_physical_size(chip, &phys);
    if (err == ESP_OK) {
        PROBE("flash.physical_size", "%" PRIu32, phys);
    } else {
        PROBE("flash.physical_size", "error:%s", esp_err_to_name(err));
    }
    uint32_t conf = 0;
    err = esp_flash_get_size(chip, &conf);
    if (err == ESP_OK) {
        PROBE("flash.configured_size", "%" PRIu32, conf);
    } else {
        PROBE("flash.configured_size", "error:%s", esp_err_to_name(err));
    }

    uint64_t uid = 0;
    err = esp_flash_read_unique_chip_id(chip, &uid);
    if (err == ESP_OK) {
        PROBE("flash.unique_id", "0x%016" PRIx64, uid);
    } else {
        PROBE("flash.unique_id", "error:%s", esp_err_to_name(err));
    }

    /* Bootloader image header at 0x0: magic, segment count, SPI mode, size/freq nibbles. */
    uint8_t hdr[4] = {0};
    err = esp_flash_read(chip, hdr, 0x0, sizeof(hdr));
    if (err == ESP_OK) {
        PROBE("flash.boot_header", "magic:0x%02x,segments:%u,spi_mode:%u,size_freq:0x%02x", hdr[0],
              hdr[1], hdr[2], hdr[3]);
    } else {
        PROBE("flash.boot_header", "error:%s", esp_err_to_name(err));
    }

    /* Read throughput over 1 MB starting at the running app (read-only). */
    const esp_partition_t *app = esp_ota_get_running_partition();
    uint8_t *buf = heap_caps_malloc(FLASH_READ_CHUNK, MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    if (app == NULL || buf == NULL) {
        PROBE("flash.read_test", "not_run:no_buffer_or_partition");
        free(buf);
        return;
    }
    uint32_t len = app->size < FLASH_READ_TEST_BYTES ? app->size : FLASH_READ_TEST_BYTES;
    uint32_t sum = 0;
    int64_t t0 = esp_timer_get_time();
    int64_t paused_us = 0;
    for (uint32_t off = 0; off < len; off += FLASH_READ_CHUNK) {
        err = esp_flash_read(chip, buf, app->address + off, FLASH_READ_CHUNK);
        if (err != ESP_OK) {
            break;
        }
        for (uint32_t i = 0; i < FLASH_READ_CHUNK; i += 64) {
            sum += buf[i];
        }
        if ((off & 0xFFFF) == 0) {
            int64_t p0 = esp_timer_get_time();
            vTaskDelay(1);
            paused_us += esp_timer_get_time() - p0;
        }
    }
    int64_t dt = esp_timer_get_time() - t0 - paused_us;
    free(buf);
    if (err != ESP_OK) {
        PROBE("flash.read_test", "error:%s", esp_err_to_name(err));
        return;
    }
    PROBE("flash.read_test_bytes", "%" PRIu32, len);
    PROBE("flash.read_test_offset", "0x%06" PRIx32, app->address);
    PROBE("flash.read_test_us", "%" PRId64, dt);
    PROBE("flash.read_mb_per_s", "%.2f", dt > 0 ? (double)len / (double)dt : 0.0);
    PROBE("flash.read_test_checksum", "0x%08" PRIx32, sum);
}

/* ---------------------------------------------------------------- PSRAM */

#define PSRAM_MAX_CHUNKS 64
#define PSRAM_CHUNK_MAX (1024U * 1024U)
#define PSRAM_CHUNK_MIN (16U * 1024U)
#define PSRAM_ALIGN 64U

typedef enum {
    PAT_ADDR = 0,
    PAT_NOT_ADDR,
    PAT_55,
    PAT_AA,
    PAT_WALK1,
    PAT_WALK0,
    PAT_COUNT,
} pattern_t;

static const char *const PAT_NAMES[PAT_COUNT] = {"addr", "not_addr", "x55", "xaa", "walk1", "walk0"};

static inline uint32_t pattern_value(pattern_t p, uintptr_t addr, uint32_t index)
{
    switch (p) {
    case PAT_ADDR: return (uint32_t)addr;
    case PAT_NOT_ADDR: return ~(uint32_t)addr;
    case PAT_55: return 0x55555555U;
    case PAT_AA: return 0xAAAAAAAAU;
    case PAT_WALK1: return 1U << (index & 31U);
    default: return ~(1U << (index & 31U));
    }
}

void probe_psram(void)
{
    bool init = esp_psram_is_initialized();
    PROBE("psram.initialized", "%d", init ? 1 : 0);
#ifdef CONFIG_SPIRAM_MODE_OCT
    PROBE("psram.config_mode", "oct");
#else
    PROBE("psram.config_mode", "quad");
#endif
    PROBE("psram.config_speed_mhz", "%d", CONFIG_SPIRAM_SPEED);
    if (!init) {
        PROBE("psram.test", "not_run:not_initialized");
        return;
    }
    PROBE("psram.size", "%u", (unsigned)esp_psram_get_size());

    static uint32_t *chunks[PSRAM_MAX_CHUNKS];
    static size_t sizes[PSRAM_MAX_CHUNKS];
    size_t n = 0;
    size_t total = 0;
    size_t want = PSRAM_CHUNK_MAX;
    while (n < PSRAM_MAX_CHUNKS && want >= PSRAM_CHUNK_MIN) {
        void *p = heap_caps_aligned_alloc(PSRAM_ALIGN, want, MALLOC_CAP_SPIRAM);
        if (p == NULL) {
            want /= 2;
            continue;
        }
        chunks[n] = p;
        sizes[n] = want;
        total += want;
        n++;
    }
    PROBE("psram.test_bytes", "%u", (unsigned)total);
    PROBE("psram.test_chunks", "%u", (unsigned)n);

    int sync_errors = 0;
    double write_mbps = 0;
    double read_mbps = 0;
    for (int p = 0; p < PAT_COUNT; p++) {
        uint32_t errors = 0;
        uintptr_t first_bad = 0;
        uint32_t first_got = 0;
        uint32_t first_want = 0;
        int64_t tw = 0;
        int64_t tr = 0;
        uint32_t index = 0;
        for (size_t c = 0; c < n; c++) {
            volatile uint32_t *w = chunks[c];
            size_t words = sizes[c] / 4;
            int64_t t0 = esp_timer_get_time();
            for (size_t i = 0; i < words; i++) {
                w[i] = pattern_value((pattern_t)p, (uintptr_t)&w[i], index + (uint32_t)i);
            }
            tw += esp_timer_get_time() - t0;
            /* Write back and drop cached lines so the verify pass reads the PSRAM itself. */
            if (esp_cache_msync(chunks[c], sizes[c],
                                ESP_CACHE_MSYNC_FLAG_DIR_C2M | ESP_CACHE_MSYNC_FLAG_INVALIDATE) !=
                ESP_OK) {
                sync_errors++;
            }
            index += (uint32_t)words;
            vTaskDelay(1);
        }
        index = 0;
        for (size_t c = 0; c < n; c++) {
            volatile uint32_t *r = chunks[c];
            size_t words = sizes[c] / 4;
            int64_t t0 = esp_timer_get_time();
            for (size_t i = 0; i < words; i++) {
                uint32_t want_v = pattern_value((pattern_t)p, (uintptr_t)&r[i], index + (uint32_t)i);
                uint32_t got = r[i];
                if (got != want_v) {
                    if (errors == 0) {
                        first_bad = (uintptr_t)&r[i];
                        first_got = got;
                        first_want = want_v;
                    }
                    errors++;
                }
            }
            tr += esp_timer_get_time() - t0;
            index += (uint32_t)words;
            vTaskDelay(1);
        }
        printf("PROBE psram.pattern_%s=errors:%" PRIu32 ",first_bad:0x%08x,got:0x%08" PRIx32
               ",want:0x%08" PRIx32 "\n",
               PAT_NAMES[p], errors, (unsigned)first_bad, first_got, first_want);
        if (p == PAT_55) {
            write_mbps = tw > 0 ? (double)total / (double)tw : 0.0;
            read_mbps = tr > 0 ? (double)total / (double)tr : 0.0;
        }
    }
    for (size_t c = 0; c < n; c++) {
        heap_caps_free(chunks[c]);
    }
    PROBE("psram.cache_sync_errors", "%d", sync_errors);
    /* Measured on the constant 0x55 pattern; loop overhead included (CPU word loop). */
    PROBE("psram.write_mb_per_s", "%.2f", write_mbps);
    PROBE("psram.read_mb_per_s", "%.2f", read_mbps);
}
