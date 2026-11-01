#include "display.h"

#include <string.h>

#include "board.h"
#include "driver/i2c_master.h"
#include "esp_check.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_ssd1306.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"

static const char *TAG = "display";

/* The SSD1306 addresses memory in pages of 8 vertical pixels, so the
 * framebuffer is stored the same way and can be handed to the panel driver
 * untouched: byte (page * width + x) holds the column of 8 pixels starting
 * at y = page * 8, LSB topmost. */
#define PAGES (OLED_HEIGHT / 8)

static uint8_t s_fb[OLED_WIDTH * PAGES];
static esp_lcd_panel_handle_t s_panel;

/* Classic 5x7 glyphs, five column bytes each, covering ASCII 0x20..0x5F.
 * Stopping at 0x5F keeps the table small and is enough for a remote whose UI
 * is all uppercase; display_text() folds lowercase up into this range. */
static const uint8_t FONT[][5] = {
    {0x00, 0x00, 0x00, 0x00, 0x00},  /*   */  {0x00, 0x00, 0x5F, 0x00, 0x00},  /* ! */
    {0x00, 0x07, 0x00, 0x07, 0x00},  /* " */  {0x14, 0x7F, 0x14, 0x7F, 0x14},  /* # */
    {0x24, 0x2A, 0x7F, 0x2A, 0x12},  /* $ */  {0x23, 0x13, 0x08, 0x64, 0x62},  /* % */
    {0x36, 0x49, 0x55, 0x22, 0x50},  /* & */  {0x00, 0x05, 0x03, 0x00, 0x00},  /* ' */
    {0x00, 0x1C, 0x22, 0x41, 0x00},  /* ( */  {0x00, 0x41, 0x22, 0x1C, 0x00},  /* ) */
    {0x14, 0x08, 0x3E, 0x08, 0x14},  /* * */  {0x08, 0x08, 0x3E, 0x08, 0x08},  /* + */
    {0x00, 0x50, 0x30, 0x00, 0x00},  /* , */  {0x08, 0x08, 0x08, 0x08, 0x08},  /* - */
    {0x00, 0x60, 0x60, 0x00, 0x00},  /* . */  {0x20, 0x10, 0x08, 0x04, 0x02},  /* / */
    {0x3E, 0x51, 0x49, 0x45, 0x3E},  /* 0 */  {0x00, 0x42, 0x7F, 0x40, 0x00},  /* 1 */
    {0x42, 0x61, 0x51, 0x49, 0x46},  /* 2 */  {0x21, 0x41, 0x45, 0x4B, 0x31},  /* 3 */
    {0x18, 0x14, 0x12, 0x7F, 0x10},  /* 4 */  {0x27, 0x45, 0x45, 0x45, 0x39},  /* 5 */
    {0x3C, 0x4A, 0x49, 0x49, 0x30},  /* 6 */  {0x01, 0x71, 0x09, 0x05, 0x03},  /* 7 */
    {0x36, 0x49, 0x49, 0x49, 0x36},  /* 8 */  {0x06, 0x49, 0x49, 0x29, 0x1E},  /* 9 */
    {0x00, 0x36, 0x36, 0x00, 0x00},  /* : */  {0x00, 0x56, 0x36, 0x00, 0x00},  /* ; */
    {0x08, 0x14, 0x22, 0x41, 0x00},  /* < */  {0x14, 0x14, 0x14, 0x14, 0x14},  /* = */
    {0x00, 0x41, 0x22, 0x14, 0x08},  /* > */  {0x02, 0x01, 0x51, 0x09, 0x06},  /* ? */
    {0x32, 0x49, 0x79, 0x41, 0x3E},  /* @ */  {0x7E, 0x11, 0x11, 0x11, 0x7E},  /* A */
    {0x7F, 0x49, 0x49, 0x49, 0x36},  /* B */  {0x3E, 0x41, 0x41, 0x41, 0x22},  /* C */
    {0x7F, 0x41, 0x41, 0x22, 0x1C},  /* D */  {0x7F, 0x49, 0x49, 0x49, 0x41},  /* E */
    {0x7F, 0x09, 0x09, 0x09, 0x01},  /* F */  {0x3E, 0x41, 0x49, 0x49, 0x7A},  /* G */
    {0x7F, 0x08, 0x08, 0x08, 0x7F},  /* H */  {0x00, 0x41, 0x7F, 0x41, 0x00},  /* I */
    {0x20, 0x40, 0x41, 0x3F, 0x01},  /* J */  {0x7F, 0x08, 0x14, 0x22, 0x41},  /* K */
    {0x7F, 0x40, 0x40, 0x40, 0x40},  /* L */  {0x7F, 0x02, 0x0C, 0x02, 0x7F},  /* M */
    {0x7F, 0x04, 0x08, 0x10, 0x7F},  /* N */  {0x3E, 0x41, 0x41, 0x41, 0x3E},  /* O */
    {0x7F, 0x09, 0x09, 0x09, 0x06},  /* P */  {0x3E, 0x41, 0x51, 0x21, 0x5E},  /* Q */
    {0x7F, 0x09, 0x19, 0x29, 0x46},  /* R */  {0x46, 0x49, 0x49, 0x49, 0x31},  /* S */
    {0x01, 0x01, 0x7F, 0x01, 0x01},  /* T */  {0x3F, 0x40, 0x40, 0x40, 0x3F},  /* U */
    {0x1F, 0x20, 0x40, 0x20, 0x1F},  /* V */  {0x3F, 0x40, 0x38, 0x40, 0x3F},  /* W */
    {0x63, 0x14, 0x08, 0x14, 0x63},  /* X */  {0x07, 0x08, 0x70, 0x08, 0x07},  /* Y */
    {0x61, 0x51, 0x49, 0x45, 0x43},  /* Z */  {0x00, 0x7F, 0x41, 0x41, 0x00},  /* [ */
    {0x02, 0x04, 0x08, 0x10, 0x20},  /* \ */  {0x00, 0x41, 0x41, 0x7F, 0x00},  /* ] */
    {0x04, 0x02, 0x01, 0x02, 0x04},  /* ^ */  {0x40, 0x40, 0x40, 0x40, 0x40},  /* _ */
};

#define FONT_FIRST 0x20
#define FONT_LAST  0x5F

esp_err_t display_init(void)
{
    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    i2c_master_bus_handle_t bus = NULL;
    ESP_RETURN_ON_ERROR(i2c_new_master_bus(&bus_cfg, &bus), TAG, "i2c bus");

    esp_lcd_panel_io_i2c_config_t io_cfg = {
        .dev_addr = OLED_I2C_ADDR,
        .scl_speed_hz = 400 * 1000,
        .control_phase_bytes = 1,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .dc_bit_offset = 6,
    };
    esp_lcd_panel_io_handle_t io = NULL;
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_i2c(bus, &io_cfg, &io), TAG, "panel io");

    esp_lcd_panel_ssd1306_config_t vendor_cfg = { .height = OLED_HEIGHT };
    esp_lcd_panel_dev_config_t panel_cfg = {
        .bits_per_pixel = 1,
        .reset_gpio_num = -1,          /* module ties RES high itself */
        .vendor_config = &vendor_cfg,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_ssd1306(io, &panel_cfg, &s_panel), TAG, "panel");

    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "reset");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "init");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(s_panel, true), TAG, "on");

    display_clear();
    ESP_LOGI(TAG, "SSD1306 %dx%d up on SDA=%d SCL=%d addr=0x%02X",
             OLED_WIDTH, OLED_HEIGHT, PIN_I2C_SDA, PIN_I2C_SCL, OLED_I2C_ADDR);
    return display_flush();
}

esp_err_t display_flush(void)
{
    return esp_lcd_panel_draw_bitmap(s_panel, 0, 0, OLED_WIDTH, OLED_HEIGHT, s_fb);
}

void display_clear(void)
{
    memset(s_fb, 0, sizeof(s_fb));
}

void display_pixel(int x, int y, bool on)
{
    if (x < 0 || x >= OLED_WIDTH || y < 0 || y >= OLED_HEIGHT) {
        return;
    }
    uint8_t *cell = &s_fb[(y / 8) * OLED_WIDTH + x];
    uint8_t mask = 1u << (y % 8);
    if (on) {
        *cell |= mask;
    } else {
        *cell &= (uint8_t)~mask;
    }
}

static int draw_char(int x, int y, char c, bool inverted)
{
    if (c >= 'a' && c <= 'z') {
        c = (char)(c - 'a' + 'A');
    }
    const uint8_t *glyph;
    uint8_t unknown[5] = {0x7F, 0x41, 0x41, 0x41, 0x7F};  /* box for out-of-range */
    if (c < FONT_FIRST || c > FONT_LAST) {
        glyph = unknown;
    } else {
        glyph = FONT[c - FONT_FIRST];
    }

    for (int col = 0; col < DISPLAY_FONT_W; col++) {
        for (int row = 0; row < DISPLAY_FONT_H; row++) {
            bool lit = (glyph[col] >> row) & 1;
            display_pixel(x + col, y + row, inverted ? !lit : lit);
        }
    }
    if (inverted) {
        /* Fill the inter-character gap so inverted runs look continuous. */
        for (int row = 0; row < DISPLAY_FONT_H; row++) {
            display_pixel(x + DISPLAY_FONT_W, y + row, true);
        }
    }
    return x + DISPLAY_ADVANCE;
}

static int draw_text(int x, int y, const char *s, bool inverted)
{
    for (; *s; s++) {
        x = draw_char(x, y, *s, inverted);
    }
    return x;
}

int display_text(int x, int y, const char *s) { return draw_text(x, y, s, false); }
int display_text_inverted(int x, int y, const char *s) { return draw_text(x, y, s, true); }

void display_hline(int x, int y, int w, bool on)
{
    for (int i = 0; i < w; i++) {
        display_pixel(x + i, y, on);
    }
}

void display_vline(int x, int y, int h, bool on)
{
    for (int i = 0; i < h; i++) {
        display_pixel(x, y + i, on);
    }
}

void display_rect(int x, int y, int w, int h, bool on)
{
    display_hline(x, y, w, on);
    display_hline(x, y + h - 1, w, on);
    display_vline(x, y, h, on);
    display_vline(x + w - 1, y, h, on);
}

void display_fill(int x, int y, int w, int h, bool on)
{
    for (int row = 0; row < h; row++) {
        display_hline(x, y + row, w, on);
    }
}

void display_bar(int x, int y, int w, int h, int value, int max, int marker)
{
    if (max <= 0) {
        return;
    }
    if (value < 0) {
        value = 0;
    }
    if (value > max) {
        value = max;
    }

    display_rect(x, y, w, h, true);
    int inner = w - 4;
    int filled = (inner * value) / max;
    if (filled > 0) {
        display_fill(x + 2, y + 2, filled, h - 4, true);
    }

    if (marker >= 0) {
        int mx = x + 2 + (inner * marker) / max;
        /* A three-pixel caret under the bar, clamped inside its width. */
        if (mx < x + 1) {
            mx = x + 1;
        }
        if (mx > x + w - 2) {
            mx = x + w - 2;
        }
        display_pixel(mx, y + h + 1, true);
        display_pixel(mx - 1, y + h + 2, true);
        display_pixel(mx, y + h + 2, true);
        display_pixel(mx + 1, y + h + 2, true);
    }
}
