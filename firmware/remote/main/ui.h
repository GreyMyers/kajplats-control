/* Key handling for the screenless remote.
 *
 * With no display there is no way to show hidden state, so the map avoids
 * having any. An earlier draft used `#` to flip between a brightness mode
 * and a white mode, which is fine with a screen telling you which is live
 * and unusable without one: every press becomes a guess.
 *
 * So brightness — by far the most-used control — is unconditional, and
 * white temperature sits behind a momentary shift that announces itself on
 * the LED and times out on its own:
 *
 *   1..9       brightness, 11% to 100%            (always, no mode)
 *   # then 1..9  white temperature, 2202K to 6535K (LED on while armed)
 *   #  alone   (after the timeout) arms the shift again
 *   *          toggle power
 *   0          cycle target: BULB 1 -> BULB 2 -> BOTH, blinked back on the LED
 *
 * The shift is momentary rather than sticky precisely so that forgetting
 * about it cannot leave the remote in a state you cannot see. Worst case you
 * wait a second and the thing is plain again.
 */
#pragma once

#include "keypad.h"

/* How long `#` stays armed before reverting to plain brightness. */
#define UI_SHIFT_TIMEOUT_MS 3000

void ui_init(void);
void ui_handle_key(key_t key);

/* Drives the shift timeout and any LED animation. Call every scan. */
void ui_tick(void);
