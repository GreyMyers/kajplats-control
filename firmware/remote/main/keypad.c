#include "keypad.h"

#include "board.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "keypad";

static const int ROW_PINS[KEYPAD_ROWS] = KEYPAD_ROW_PINS;
static const int COL_PINS[KEYPAD_COLS] = KEYPAD_COL_PINS;

static const char LAYOUT[KEYPAD_ROWS][KEYPAD_COLS] = {
    {'1', '2', '3'},
    {'4', '5', '6'},
    {'7', '8', '9'},
    {'*', '0', '#'},
};

/* Debounce by requiring the same reading twice in a row. At a 20 ms scan
 * that is 40 ms of settling, comfortably past the bounce of a membrane or
 * tactile switch without feeling laggy. */
static key_t s_stable = KEY_NONE;
static key_t s_candidate = KEY_NONE;

void keypad_init(void)
{
    for (int r = 0; r < KEYPAD_ROWS; r++) {
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << ROW_PINS[r],
            .mode = GPIO_MODE_INPUT,
            .pull_up_en = GPIO_PULLUP_ENABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&cfg));
    }
    for (int c = 0; c < KEYPAD_COLS; c++) {
        gpio_config_t cfg = {
            .pin_bit_mask = 1ULL << COL_PINS[c],
            /* Open-drain so an unselected column is released rather than
             * driven high: two keys pressed in the same row would otherwise
             * short a driven-high column to a driven-low one. */
            .mode = GPIO_MODE_OUTPUT_OD,
            .pull_up_en = GPIO_PULLUP_DISABLE,
            .pull_down_en = GPIO_PULLDOWN_DISABLE,
            .intr_type = GPIO_INTR_DISABLE,
        };
        ESP_ERROR_CHECK(gpio_config(&cfg));
        gpio_set_level(COL_PINS[c], 1);  /* released */
    }
    ESP_LOGI(TAG, "4x3 matrix: rows %d,%d,%d,%d  cols %d,%d,%d",
             ROW_PINS[0], ROW_PINS[1], ROW_PINS[2], ROW_PINS[3],
             COL_PINS[0], COL_PINS[1], COL_PINS[2]);
}

static key_t read_matrix(void)
{
    for (int c = 0; c < KEYPAD_COLS; c++) {
        gpio_set_level(COL_PINS[c], 0);
        /* Let the line settle: the pull-up is weak (~45k) and the matrix has
         * real capacitance, so reading immediately catches the old level. */
        esp_rom_delay_us(20);

        for (int r = 0; r < KEYPAD_ROWS; r++) {
            if (gpio_get_level(ROW_PINS[r]) == 0) {
                gpio_set_level(COL_PINS[c], 1);
                return (key_t)LAYOUT[r][c];
            }
        }
        gpio_set_level(COL_PINS[c], 1);
    }
    return KEY_NONE;
}

key_t keypad_scan(void)
{
    key_t now = read_matrix();

    if (now != s_candidate) {
        s_candidate = now;      /* first sighting; wait for confirmation */
        return KEY_NONE;
    }
    if (now == s_stable) {
        return KEY_NONE;        /* unchanged, including a held key */
    }

    s_stable = now;
    return now;                 /* KEY_NONE on release, a key on press */
}
