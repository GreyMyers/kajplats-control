/* Pin assignment for the handheld remote.
 *
 * Constraints that drove these choices, all verified against the ESP32-C6
 * SoC headers rather than recalled:
 *   - GPIO0..GPIO7 are the LP/RTC-capable pins, and only those can drive or
 *     wake during deep sleep. The whole keypad therefore has to live in that
 *     range, or it cannot wake the chip on a keypress.
 *   - GPIO4, 5, 8, 9 and 15 are strapping pins; GPIO12/13 are USB D-/D+.
 *   - ADC1 is GPIO0..GPIO6 (unused here now that knobs are gone, but it is
 *     why the keypad was packed low rather than spread out).
 *
 * The keypad needs 7 pins and only 8 LP pins exist, so one strapping pin
 * (GPIO5) is unavoidable. It is safe in practice: at reset the column pins
 * are high-Z and the row pull-ups are not yet enabled, so a key held during
 * power-on cannot assert a level on it.
 */
#pragma once

#define PIN_I2C_SDA        10
#define PIN_I2C_SCL        11
#define OLED_I2C_ADDR      0x3C
#define OLED_WIDTH         128
#define OLED_HEIGHT        64

/* 4x3 matrix: columns are driven low one at a time, rows are read with
 * pull-ups. For deep-sleep wake later, all columns are held low and any row
 * going low wakes the chip. */
#define KEYPAD_ROWS        4
#define KEYPAD_COLS        3
#define KEYPAD_ROW_PINS    { 0, 1, 2, 3 }
#define KEYPAD_COL_PINS    { 5, 6, 7 }
