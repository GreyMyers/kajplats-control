/* Pin assignment for the handheld remote — Seeed XIAO ESP32C6.
 *
 * The XIAO breaks out only eleven GPIOs, and three more are spoken for on
 * the board itself:
 *
 *   GPIO3   RF switch enable, ACTIVE LOW. Left floating the antenna is
 *           effectively disconnected and the radio barely works - which
 *           presents as a bad mesh, not as a pin mistake. board_init()
 *           drives it low.
 *   GPIO14  Antenna select: low = onboard ceramic, high = external U.FL.
 *   GPIO15  User LED.
 *
 * Header mapping, for cross-checking against the silkscreen:
 *   D0=0  D1=1  D2=2  D3=21  D4=22(SDA)  D5=23(SCL)
 *   D6=16 D7=17 D8=19 D9=20  D10=18
 *
 * Deep-sleep wake needs LP/RTC-capable pins, which on the C6 are GPIO0..7 —
 * and of those the XIAO exposes only GPIO0, GPIO1 and GPIO2. Three of the
 * four keypad rows can therefore wake the chip and the fourth cannot, so the
 * rows are deliberately wired out of order: the `* 0 #` row goes to a
 * wake-capable pin and `7 8 9` takes the one that cannot wake. A remote
 * whose power key does not wake it would be a poor remote; failing to wake
 * on 7/8/9 is a far smaller loss.
 *
 * For full wake coverage on all twelve keys, feed all four row lines into
 * one spare LP pin through signal diodes (cathodes to the rows) and wake on
 * that instead. That costs four diodes and is not worth it unless missing
 * 7/8/9 proves annoying.
 */
#pragma once

/* --- board-reserved ------------------------------------------------------ */
#define PIN_RF_SWITCH_EN   3    /* drive LOW to enable the RF switch */
#define PIN_ANTENNA_SEL    14   /* LOW = onboard ceramic antenna */
#define PIN_USER_LED       15

/* --- display: the XIAO's default I2C pads -------------------------------- */
#define PIN_I2C_SDA        22   /* D4 */
#define PIN_I2C_SCL        23   /* D5 */
#define OLED_I2C_ADDR      0x3C
#define OLED_WIDTH         128
#define OLED_HEIGHT        64

/* --- keypad: 4x3 matrix --------------------------------------------------
 * Columns are driven low one at a time; rows are read with pull-ups.
 * Row order is intentionally not 1-2-3-4: see the note above.
 *
 *   row index 0 -> GPIO0  (D0)  keys 1 2 3   wake-capable
 *   row index 1 -> GPIO1  (D1)  keys 4 5 6   wake-capable
 *   row index 2 -> GPIO2  (D2)  keys * 0 #   wake-capable
 *   row index 3 -> GPIO21 (D3)  keys 7 8 9   cannot wake
 */
#define KEYPAD_ROWS        4
#define KEYPAD_COLS        3
#define KEYPAD_ROW_PINS    { 0, 1, 2, 21 }
#define KEYPAD_COL_PINS    { 16, 17, 19 }

/* Bring the board's own hardware into a known state. Must run before the
 * radio is used. */
void board_init(void);
