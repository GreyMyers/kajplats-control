#include "board.h"

#include "driver/gpio.h"
#include "esp_log.h"

static const char *TAG = "board";

void board_init(void)
{
    /* The XIAO routes its antenna through an RF switch that is powered by
     * GPIO3 and steered by GPIO14. Neither has a pull on the board, so a
     * firmware that never touches them leaves the switch unpowered and the
     * antenna effectively disconnected. Thread then "works" at a few
     * centimetres and looks like a mesh problem. */
    gpio_config_t cfg = {
        .pin_bit_mask = (1ULL << PIN_RF_SWITCH_EN) | (1ULL << PIN_ANTENNA_SEL),
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&cfg));

    gpio_set_level(PIN_RF_SWITCH_EN, 0);   /* active low: switch powered */
    gpio_set_level(PIN_ANTENNA_SEL, 0);    /* onboard ceramic antenna */

    ESP_LOGI(TAG, "XIAO ESP32C6: RF switch enabled (GPIO%d low), "
                  "onboard antenna selected (GPIO%d low)",
             PIN_RF_SWITCH_EN, PIN_ANTENNA_SEL);
}
