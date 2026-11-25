# Wi-Fi components are listed so the bringup_wifi env (build flag BRINGUP_WIFI) can
# include their headers; component requirements cannot depend on build flags. In the
# default env no code references them, so nothing from the Wi-Fi stack is linked
# (checked against the linker map; see README.md).
idf_component_register(
    SRCS "main.c" "pin_policy.c" "probes_system.c" "probes_memory.c" "probes_pins.c"
         "rgb_led.c" "probes_wifi.c"
    INCLUDE_DIRS "."
    PRIV_REQUIRES esp_driver_gpio esp_driver_uart esp_driver_rmt esp_driver_tsens
                  esp_driver_usb_serial_jtag esp_adc esp_psram esp_mm spi_flash efuse
                  esp_partition app_update esp_app_format esp_timer esp_hw_support
                  esp_wifi esp_event nvs_flash
)
