/* Handheld Thread remote for IKEA KAJPLATS bulbs - UI bring-up build.
 *
 * This build has no Matter stack: lights.c only logs what it would send, so
 * the keypad, screen and interaction model can be finished on USB power
 * before any of the harder work starts. See docs/remote.md for the plan.
 */
#include "display.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "keypad.h"
#include "lights.h"
#include "ui.h"

static const char *TAG = "remote";

void app_main(void)
{
    ESP_LOGI(TAG, "KAJPLATS remote - UI bring-up build");

    ESP_ERROR_CHECK(display_init());
    keypad_init();
    lights_init();
    ui_init();
    ui_render();

    /* The screen is only redrawn when something changes. An I2C OLED takes
     * roughly 25 ms to push a full frame at 400 kHz, so redrawing every scan
     * would waste most of the loop and, later, most of the battery. */
    while (true) {
        key_t key = keypad_scan();
        if (key != KEY_NONE) {
            ESP_LOGI(TAG, "key '%c'", (char)key);
            ui_handle_key(key);
            ui_render();
        }
        vTaskDelay(pdMS_TO_TICKS(KEYPAD_SCAN_MS));
    }
}
