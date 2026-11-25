/**
 * @file probes.h
 * @brief Bring-up probe sections. Every fact is one line: ``PROBE <section>.<key>=<value>``.
 *
 * Values are raw evidence, never interpretation. printf is used (not ESP_LOGx) so
 * lines carry no log prefix or colour codes.
 */
#pragma once

#include <stdbool.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

/** Print one probe line. @p key is "<section>.<key>". */
#define PROBE(key, fmt, ...) printf("PROBE " key "=" fmt "\n", ##__VA_ARGS__)

/** Probe format version printed at report start; bump when keys change meaning. */
#define PROBE_FORMAT_VERSION 1

/* probes_system.c */
void probe_build_and_clocks(void);
void probe_chip_and_efuse(void);
void probe_strap_latch(void);
void probe_heap_and_partitions(void);
void probe_temperature(void);
void probe_brownout(void);
void probe_usb(void);

/* probes_memory.c */
void probe_flash(void);
void probe_psram(void);

/* probes_pins.c */
void probe_xtal32k(void);
void probe_pin_scan(void);
void probe_adc_scan(void);

/**
 * @brief Interactive header walk test (pull-ups on candidates, report transitions).
 * @param stop_requested Returns true when the operator pressed a key.
 */
void probe_walk(bool (*stop_requested)(void));

/**
 * @brief Drive one pin high 2 s, low 2 s, then release it. Requires armed policy.
 * @param gpio GPIO number.
 * @param section Probe section name used in output ("drive" or "sweep").
 */
void probe_drive_pin(int gpio, const char *section);

/** @brief Start the BOOT button (GPIO0) monitor task. */
void boot_button_start(void);

#ifdef BRINGUP_WIFI
/* probes_wifi.c */
void probe_wifi_scan(void);
#endif

#ifdef __cplusplus
}
#endif
