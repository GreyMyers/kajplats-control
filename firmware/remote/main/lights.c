#include "lights.h"

#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "lights";

/* Rate limiting, carried over from the desktop app for the same reason: a
 * burst of commands is more than a Thread mesh will absorb, and the only one
 * that matters is the last. Keypad presses are far slower than this in
 * practice, but a held key or a bounce storm must not turn into a flood once
 * this is talking to real bulbs.
 */
#define MIN_INTERVAL_US 100000  /* 100 ms per channel */

typedef enum { CH_POWER = 0, CH_LEVEL, CH_MIREDS, CH_COUNT } channel_t;

static int64_t s_last_sent[TARGET_COUNT][CH_COUNT];

static bool allow(light_target_t target, channel_t ch)
{
    int64_t now = esp_timer_get_time();
    if (now - s_last_sent[target][ch] < MIN_INTERVAL_US) {
        return false;
    }
    s_last_sent[target][ch] = now;
    return true;
}

const char *light_target_name(light_target_t target)
{
    switch (target) {
        case TARGET_A:    return "BULB 1";
        case TARGET_B:    return "BULB 2";
        case TARGET_BOTH: return "BOTH";
        default:          return "?";
    }
}

void lights_init(void)
{
    ESP_LOGI(TAG, "transport: log-only stub (no Matter stack yet)");
}

void lights_set_power(light_target_t target, bool on)
{
    if (!allow(target, CH_POWER)) {
        return;
    }
    ESP_LOGI(TAG, "%-6s OnOff.%s", light_target_name(target), on ? "On" : "Off");
}

void lights_set_level(light_target_t target, uint8_t level)
{
    if (!allow(target, CH_LEVEL)) {
        return;
    }
    ESP_LOGI(TAG, "%-6s LevelControl.MoveToLevelWithOnOff level=%u (%u%%)",
             light_target_name(target), level,
             (unsigned)((level - LEVEL_MIN) * 100u / (LEVEL_MAX - LEVEL_MIN)));
}

void lights_set_mireds(light_target_t target, uint16_t mireds)
{
    if (!allow(target, CH_MIREDS)) {
        return;
    }
    ESP_LOGI(TAG, "%-6s ColorControl.MoveToColorTemperature mireds=%u (%uK)",
             light_target_name(target), mireds, mireds_to_kelvin(mireds));
}
