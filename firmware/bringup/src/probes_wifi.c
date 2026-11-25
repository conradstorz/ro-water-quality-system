/**
 * @file probes_wifi.c
 * @brief Opt-in (env ``bringup_wifi``) passive Wi-Fi scan to judge which antenna
 *        (PCB or IPEX) is active. Passive scan = receive only, no probe requests.
 *
 * SSIDs are not printed (neighbours' network names do not belong in a bench log);
 * BSSIDs identify the same AP across runs with different antenna set-ups.
 */
#ifdef BRINGUP_WIFI

#include <inttypes.h>
#include <string.h>

#include "esp_err.h"
#include "esp_event.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "probes.h"

#define WIFI_TOP_N 8
#define PASSIVE_DWELL_MS 300

static bool s_wifi_ready;

static esp_err_t wifi_bring_up(void)
{
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err != ESP_OK) {
        return err;
    }
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&cfg);
    if (err == ESP_OK) {
        err = esp_wifi_set_mode(WIFI_MODE_STA);
    }
    if (err == ESP_OK) {
        err = esp_wifi_start();
    }
    return err;
}

void probe_wifi_scan(void)
{
    if (!s_wifi_ready) {
        esp_err_t err = wifi_bring_up();
        if (err != ESP_OK) {
            PROBE("wifi.init", "error:%s", esp_err_to_name(err));
            return;
        }
        s_wifi_ready = true;
    }
    wifi_scan_config_t sc = {
        .show_hidden = true,
        .scan_type = WIFI_SCAN_TYPE_PASSIVE,
        .scan_time.passive = PASSIVE_DWELL_MS,
    };
    PROBE("wifi.scan_type", "passive");
    PROBE("wifi.dwell_ms", "%d", PASSIVE_DWELL_MS);
    esp_err_t err = esp_wifi_scan_start(&sc, true);
    if (err != ESP_OK) {
        PROBE("wifi.scan", "error:%s", esp_err_to_name(err));
        return;
    }
    uint16_t count = 0;
    esp_wifi_scan_get_ap_num(&count);
    PROBE("wifi.ap_count", "%u", (unsigned)count);
    wifi_ap_record_t recs[WIFI_TOP_N];
    uint16_t n = WIFI_TOP_N;
    memset(recs, 0, sizeof(recs));
    err = esp_wifi_scan_get_ap_records(&n, recs);
    if (err != ESP_OK) {
        PROBE("wifi.records", "error:%s", esp_err_to_name(err));
        return;
    }
    for (uint16_t i = 0; i < n; i++) {
        const uint8_t *b = recs[i].bssid;
        printf("PROBE wifi.ap%u=rssi:%d,channel:%u,bssid:%02x:%02x:%02x:%02x:%02x:%02x\n",
               (unsigned)i, recs[i].rssi, (unsigned)recs[i].primary, b[0], b[1], b[2], b[3], b[4],
               b[5]);
    }
}

#endif /* BRINGUP_WIFI */
