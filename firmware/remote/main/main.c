/* Handheld Thread remote for IKEA KAJPLATS bulbs - keypad bring-up build.
 *
 * No display and no Matter stack yet: lights.c logs what it would send, so
 * the keypad and interaction model can be finished before either arrives.
 * See docs/remote.md.
 */
#include "board.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "keypad.h"
#include "led.h"
#include "lights.h"
#include "ui.h"

static const char *TAG = "remote";

void app_main(void)
{
    ESP_LOGI(TAG, "KAJPLATS remote - keypad bring-up build");

    /* Before anything else: on the XIAO the radio is useless until the RF
     * switch is powered. */
    board_init();

    led_init();
    keypad_init();
    lights_init();
    ui_init();

    while (true) {
        key_t key = keypad_scan();
        if (key != KEY_NONE) {
            ui_handle_key(key);
        }
        ui_tick();
        vTaskDelay(pdMS_TO_TICKS(KEYPAD_SCAN_MS));
    }
}
