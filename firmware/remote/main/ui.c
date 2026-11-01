#include "ui.h"

#include "board.h"
#include "esp_log.h"
#include "led.h"
#include "lights.h"

static const char *TAG = "ui";

#define STEPS 9

static struct {
    bool on;
    uint8_t level;
    uint16_t mireds;
    light_target_t target;
    int shift_ms_left;      /* >0 while `#` has armed the white-temperature shift */
} s;

/* Nine evenly spaced stops on each axis. Brightness starts at 1/9 rather
 * than zero so key 1 is "dim", not "off" - turning the bulbs off is what the
 * dedicated * key is for. */
static uint8_t step_to_level(int step)
{
    return (uint8_t)(LEVEL_MIN + ((LEVEL_MAX - LEVEL_MIN) * step) / STEPS);
}

static uint16_t step_to_mireds(int step)
{
    /* Warm on 1, cool on 9. Mireds run opposite to kelvin, so this counts
     * down from the warm end. */
    int span = MIREDS_MAX - MIREDS_MIN;
    return (uint16_t)(MIREDS_MAX - (span * (step - 1)) / (STEPS - 1));
}

void ui_init(void)
{
    s.on = true;
    s.level = step_to_level(STEPS);
    s.mireds = step_to_mireds(3);
    s.target = TARGET_BOTH;
    s.shift_ms_left = 0;
    ESP_LOGI(TAG, "ready: target=%s level=%u mireds=%u",
             light_target_name(s.target), s.level, s.mireds);
    ESP_LOGI(TAG, "keys: 1-9 brightness | # then 1-9 white | * power | 0 target");
}

static void disarm_shift(void)
{
    if (s.shift_ms_left > 0) {
        s.shift_ms_left = 0;
        led_set(false);
    }
}

void ui_handle_key(key_t key)
{
    switch (key) {
        case KEY_NONE:
            return;

        case KEY_STAR:
            disarm_shift();
            s.on = !s.on;
            lights_set_power(s.target, s.on);
            /* One blink for on, two for off - enough to tell them apart
             * without needing to see the bulbs, which may be in another room. */
            led_blink(s.on ? 1 : 2);
            break;

        case KEY_0:
            disarm_shift();
            s.target = (light_target_t)((s.target + 1) % TARGET_COUNT);
            /* Blink the target back: 1 = bulb 1, 2 = bulb 2, 3 = both. This
             * is the only state the user cannot otherwise observe. */
            led_blink((int)s.target + 1);
            ESP_LOGI(TAG, "target -> %s", light_target_name(s.target));
            break;

        case KEY_HASH:
            /* Momentary shift. Pressing it again while armed just restarts
             * the timer, which is harmless and matches what a user expects
             * from a key that does not visibly latch. */
            s.shift_ms_left = UI_SHIFT_TIMEOUT_MS;
            led_set(true);
            ESP_LOGI(TAG, "white shift armed (%d ms)", UI_SHIFT_TIMEOUT_MS);
            break;

        default: {
            int step = key - '0';
            if (step < 1 || step > STEPS) {
                return;
            }
            if (s.shift_ms_left > 0) {
                disarm_shift();
                s.mireds = step_to_mireds(step);
                lights_set_mireds(s.target, s.mireds);
            } else {
                s.level = step_to_level(step);
                /* MoveToLevelWithOnOff wakes a bulb that was off, so track
                 * that rather than reporting a stale off state. */
                s.on = true;
                lights_set_level(s.target, s.level);
            }
            break;
        }
    }
}

void ui_tick(void)
{
    if (s.shift_ms_left > 0) {
        s.shift_ms_left -= KEYPAD_SCAN_MS;
        if (s.shift_ms_left <= 0) {
            s.shift_ms_left = 0;
            led_set(false);
            ESP_LOGI(TAG, "white shift expired");
        }
    }
    led_tick(KEYPAD_SCAN_MS);
}
