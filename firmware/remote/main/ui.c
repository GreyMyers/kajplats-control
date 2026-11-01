#include "ui.h"

#include <stdio.h>

#include "board.h"
#include "display.h"
#include "esp_log.h"
#include "lights.h"

static const char *TAG = "ui";

#define STEPS 9

typedef enum { AXIS_BRIGHT = 0, AXIS_WHITE } axis_t;

static struct {
    bool on;
    uint8_t level;
    uint16_t mireds;
    light_target_t target;
    axis_t axis;
    int bright_step;   /* 1..9, or 0 when the current value matches no step */
    int white_step;
} s;

/* Nine evenly spaced stops on each axis. Brightness starts at 1/9 rather
 * than zero so key 1 is "dim", not "off" - turning the light off is what the
 * dedicated * key is for. */
static uint8_t step_to_level(int step)
{
    return (uint8_t)(LEVEL_MIN + ((LEVEL_MAX - LEVEL_MIN) * step) / STEPS);
}

static uint16_t step_to_mireds(int step)
{
    /* Warm on 1, cool on 9: mireds run the other way to kelvin, so this
     * counts down from MIREDS_MAX. */
    int span = MIREDS_MAX - MIREDS_MIN;
    return (uint16_t)(MIREDS_MAX - (span * (step - 1)) / (STEPS - 1));
}

void ui_init(void)
{
    s.on = true;
    s.bright_step = STEPS;
    s.white_step = 3;
    s.level = step_to_level(s.bright_step);
    s.mireds = step_to_mireds(s.white_step);
    s.target = TARGET_BOTH;
    s.axis = AXIS_BRIGHT;
    ESP_LOGI(TAG, "ready: target=%s level=%u mireds=%u",
             light_target_name(s.target), s.level, s.mireds);
}

void ui_handle_key(key_t key)
{
    switch (key) {
        case KEY_NONE:
            return;

        case KEY_STAR:
            s.on = !s.on;
            lights_set_power(s.target, s.on);
            break;

        case KEY_HASH:
            s.axis = (s.axis == AXIS_BRIGHT) ? AXIS_WHITE : AXIS_BRIGHT;
            break;

        case KEY_0:
            s.target = (light_target_t)((s.target + 1) % TARGET_COUNT);
            break;

        default: {
            int step = key - '0';
            if (step < 1 || step > STEPS) {
                return;
            }
            if (s.axis == AXIS_BRIGHT) {
                s.bright_step = step;
                s.level = step_to_level(step);
                /* MoveToLevelWithOnOff wakes a bulb that was off, so reflect
                 * that rather than showing a stale OFF. */
                s.on = true;
                lights_set_level(s.target, s.level);
            } else {
                s.white_step = step;
                s.mireds = step_to_mireds(step);
                lights_set_mireds(s.target, s.mireds);
            }
            break;
        }
    }
}

void ui_render(void)
{
    char buf[24];

    display_clear();

    /* Header: which bulbs, and whether they are on. */
    display_text(0, 0, light_target_name(s.target));
    const char *power = s.on ? "ON" : "OFF";
    int px = OLED_WIDTH - (int)(DISPLAY_ADVANCE * 3);
    if (s.on) {
        display_text_inverted(px, 0, power);
    } else {
        display_text(px, 0, power);
    }
    display_hline(0, 8, OLED_WIDTH, true);

    /* Brightness row. The active axis is inverted so it is obvious which one
     * the number keys will act on. */
    unsigned percent = (s.level - LEVEL_MIN) * 100u / (LEVEL_MAX - LEVEL_MIN);
    snprintf(buf, sizeof(buf), "BRIGHT");
    if (s.axis == AXIS_BRIGHT) {
        display_text_inverted(0, 12, buf);
    } else {
        display_text(0, 12, buf);
    }
    snprintf(buf, sizeof(buf), "%3u%%", percent);
    display_text(OLED_WIDTH - (int)(DISPLAY_ADVANCE * 4), 12, buf);
    display_bar(0, 21, OLED_WIDTH, 9, s.bright_step, STEPS, -1);

    /* White row. */
    snprintf(buf, sizeof(buf), "WHITE");
    if (s.axis == AXIS_WHITE) {
        display_text_inverted(0, 33, buf);
    } else {
        display_text(0, 33, buf);
    }
    snprintf(buf, sizeof(buf), "%4uK", mireds_to_kelvin(s.mireds));
    display_text(OLED_WIDTH - (int)(DISPLAY_ADVANCE * 5), 33, buf);
    display_bar(0, 42, OLED_WIDTH, 9, s.white_step, STEPS, -1);

    /* Footer hint. y=54 so its 7 rows end at 60: at y=58 the bottom row
     * would fall outside the 64 px panel and be silently clipped. */
    display_text(0, 54, s.axis == AXIS_BRIGHT ? "#WHITE *PWR 0TGT"
                                              : "#BRIGHT *PWR 0TGT");

    display_flush();
}
