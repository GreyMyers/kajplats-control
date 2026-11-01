/* The XIAO's user LED, used as the remote's only feedback channel.
 *
 * Kept deliberately cheap: the LED is the single largest avoidable current
 * draw on a battery device, so it is lit only in short pulses and never
 * left on except while the shift key is armed.
 */
#pragma once

#include <stdbool.h>

void led_init(void);

/* Hold the LED on or off (used to show the shift is armed). */
void led_set(bool on);

/* Queue `count` short blinks. Non-blocking; led_tick() plays them out. */
void led_blink(int count);

/* Advance any queued animation. Call every scan. */
void led_tick(int elapsed_ms);
