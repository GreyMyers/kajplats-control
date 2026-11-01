/* Screen and key handling for the remote.
 *
 * Key map, chosen around a 12-key (4x3) pad, which has no A-D row:
 *
 *   1..9   pick one of nine steps on the active axis
 *   #      switch axis: BRIGHT <-> WHITE
 *   *      toggle power
 *   0      cycle target: BULB 1 -> BULB 2 -> BOTH
 *
 * The axis idea exists because nine keys have to serve two continuous
 * controls. A dedicated preset row would need a 16-key pad.
 */
#pragma once

#include "keypad.h"

void ui_init(void);
void ui_handle_key(key_t key);
void ui_render(void);
