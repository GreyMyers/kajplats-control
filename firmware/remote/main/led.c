#include "led.h"

#include "board.h"
#include "driver/gpio.h"

/* The XIAO's user LED is active low. */
#define LED_ON_LEVEL  0
#define LED_OFF_LEVEL 1

#define BLINK_ON_MS  120
#define BLINK_OFF_MS 160

static bool s_held;
static int s_blinks_left;
static int s_phase_ms;
static bool s_blink_on;

void led_init(void)
{
    gpio_config_t cfg = {
        .pin_bit_mask = 1ULL << PIN_USER_LED,
        .mode = GPIO_MODE_OUTPUT,
        .pull_up_en = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type = GPIO_INTR_DISABLE,
    };
    gpio_config(&cfg);
    gpio_set_level(PIN_USER_LED, LED_OFF_LEVEL);
}

void led_set(bool on)
{
    s_held = on;
    if (s_blinks_left == 0) {
        gpio_set_level(PIN_USER_LED, on ? LED_ON_LEVEL : LED_OFF_LEVEL);
    }
}

void led_blink(int count)
{
    s_blinks_left = count;
    s_phase_ms = 0;
    s_blink_on = true;
    gpio_set_level(PIN_USER_LED, LED_ON_LEVEL);
}

void led_tick(int elapsed_ms)
{
    if (s_blinks_left <= 0) {
        return;
    }
    s_phase_ms += elapsed_ms;

    if (s_blink_on && s_phase_ms >= BLINK_ON_MS) {
        s_phase_ms = 0;
        s_blink_on = false;
        gpio_set_level(PIN_USER_LED, LED_OFF_LEVEL);
    } else if (!s_blink_on && s_phase_ms >= BLINK_OFF_MS) {
        s_phase_ms = 0;
        if (--s_blinks_left > 0) {
            s_blink_on = true;
            gpio_set_level(PIN_USER_LED, LED_ON_LEVEL);
        } else {
            /* Animation finished: fall back to whatever led_set() wanted. */
            gpio_set_level(PIN_USER_LED, s_held ? LED_ON_LEVEL : LED_OFF_LEVEL);
        }
    }
}
