/* Handheld Thread remote for IKEA KAJPLATS bulbs - UI bring-up build.
 *
 * This build has no Matter stack: lights.c only logs what it would send, so
 * the keypad, screen and interaction model can be finished on USB power
 * before any of the harder work starts. See docs/remote.md for the plan.
 */
#include "board.h"
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

    /* Before anything else: the radio is useless until the XIAO's RF switch
     * is powered. */
    board_init();

    /* A missing OLED must not be fatal. During bring-up the board is often
     * flashed before anything is soldered to it, and panicking there costs a
     * reboot loop and hides the keypad, which is testable on its own. */
    esp_err_t disp = display_init();
    if (disp != ESP_OK) {
        ESP_LOGW(TAG, "no OLED on I2C (%s) - running headless", esp_err_to_name(disp));
        ESP_LOGW(TAG, "key presses are logged; wire SDA=%d SCL=%d to attach one",
                 PIN_I2C_SDA, PIN_I2C_SCL);
    }

    keypad_init();
    lights_init();
    ui_init();
    ui_render();

    /* The screen is only redrawn when something changes. An I2C OLED takes
     * roughly 25 ms to push a full frame at 400 kHz, so redrawing every scan
     * would waste most of the loop and, later, most of the battery. */
    int since_probe = 0;
    while (true) {
        key_t key = keypad_scan();
        if (key != KEY_NONE) {
            ESP_LOGI(TAG, "key '%c'", (char)key);
            ui_handle_key(key);
            ui_render();
        }

        /* Re-probe every ~5 s while headless, so an OLED soldered on after
         * flashing comes to life without another flash cycle. */
        if (!display_ready() && ++since_probe >= 5000 / KEYPAD_SCAN_MS) {
            since_probe = 0;
            if (display_init() == ESP_OK) {
                ESP_LOGI(TAG, "OLED appeared");
                ui_render();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(KEYPAD_SCAN_MS));
    }
}
