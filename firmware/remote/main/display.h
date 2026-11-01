/* Monochrome 128x64 framebuffer over an SSD1306 (GME12864-13, I2C, 0x3C).
 *
 * Everything is drawn into a local buffer and pushed in one transfer, rather
 * than poking the panel per primitive: an I2C OLED is slow enough that
 * partial updates visibly tear, and one 1 KB write per frame is cheaper than
 * many small ones.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

/* Returns an error if no panel answers on the bus - which during bring-up
 * usually just means it is not wired yet. Safe to call again later to retry;
 * every other call in this header is a no-op until one succeeds. */
esp_err_t display_init(void);

bool display_ready(void);

/* Push the framebuffer to the panel. */
esp_err_t display_flush(void);

void display_clear(void);

/* Text is uppercase-only: the font covers ASCII 0x20..0x5F, and lowercase is
 * folded to uppercase when drawn. Returns the x position after the string. */
int display_text(int x, int y, const char *s);

/* Same, but inverted (lit background, dark glyphs) - used to show which of
 * the two axes the keypad is currently driving. */
int display_text_inverted(int x, int y, const char *s);

void display_pixel(int x, int y, bool on);
void display_hline(int x, int y, int w, bool on);
void display_vline(int x, int y, int h, bool on);
void display_rect(int x, int y, int w, int h, bool on);
void display_fill(int x, int y, int w, int h, bool on);

/* Horizontal bar with an outline, filled to `value` of `max`, plus a caret
 * beneath at `marker` (-1 to omit). The caret is how the UI shows a pending
 * selection that has not been sent yet. */
void display_bar(int x, int y, int w, int h, int value, int max, int marker);

#define DISPLAY_FONT_W 5
#define DISPLAY_FONT_H 7
#define DISPLAY_ADVANCE 6
