/* 4x3 matrix keypad scanner.
 *
 *      1 2 3
 *      4 5 6
 *      7 8 9
 *      * 0 #
 *
 * Columns are driven low one at a time and rows are read with internal
 * pull-ups, so a pressed key reads as a low row. That polarity is also what
 * deep-sleep wake needs later: hold every column low and wake on any row
 * going low, which is why the whole matrix sits on the LP-capable pins.
 */
#pragma once

#include <stdbool.h>

typedef enum {
    KEY_NONE = 0,
    KEY_1 = '1', KEY_2 = '2', KEY_3 = '3',
    KEY_4 = '4', KEY_5 = '5', KEY_6 = '6',
    KEY_7 = '7', KEY_8 = '8', KEY_9 = '9',
    KEY_STAR = '*', KEY_0 = '0', KEY_HASH = '#',
} key_t;

void keypad_init(void);

/* Returns the key that has just been pressed this scan, or KEY_NONE.
 * Edge-triggered: holding a key yields one event, not a stream. Call every
 * KEYPAD_SCAN_MS. */
key_t keypad_scan(void);

/* Raw matrix position of the last detected press, for checking that your
 * keypad's ribbon order matches KEYPAD_ROW_PINS / KEYPAD_COL_PINS. */
void keypad_last_position(int *row, int *col);

#define KEYPAD_SCAN_MS 20
