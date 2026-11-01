idf_component_register(
    SRCS "main.c" "board.c" "display.c" "keypad.c" "ui.c" "lights.c"
    INCLUDE_DIRS "."
    REQUIRES esp_lcd esp_driver_i2c esp_driver_gpio esp_timer)
