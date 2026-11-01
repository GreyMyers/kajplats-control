/* What the remote wants the bulbs to do.
 *
 * This is deliberately a thin seam. During UI bring-up it only logs, so the
 * whole interface can be exercised on USB power with no Matter stack, no
 * fabric and no bulbs. The Matter binding implementation drops in behind the
 * same four calls later.
 *
 * Units are Matter's own, so nothing has to be reinterpreted at the boundary:
 * level is 1..254 and colour temperature is in mireds, not kelvin.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    TARGET_A = 0,
    TARGET_B,
    TARGET_BOTH,
    TARGET_COUNT,
} light_target_t;

#define LEVEL_MIN 1
#define LEVEL_MAX 254

/* KAJPLATS E26 WS: 153..454 mireds, i.e. 6535 K down to 2202 K. Read off the
 * bulbs' ColorTempPhysicalMin/MaxMireds attributes. */
#define MIREDS_MIN 153
#define MIREDS_MAX 454

const char *light_target_name(light_target_t target);

void lights_init(void);
void lights_set_power(light_target_t target, bool on);
void lights_set_level(light_target_t target, uint8_t level);
void lights_set_mireds(light_target_t target, uint16_t mireds);

static inline uint16_t kelvin_to_mireds(uint16_t kelvin)
{
    return (uint16_t)(1000000u / (kelvin ? kelvin : 1));
}

static inline uint16_t mireds_to_kelvin(uint16_t mireds)
{
    return (uint16_t)(1000000u / (mireds ? mireds : 1));
}
