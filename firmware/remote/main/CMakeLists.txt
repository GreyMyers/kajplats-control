idf_component_register(
    SRCS "main.c" "board.c" "keypad.c" "led.c" "ui.c" "lights.c"
    INCLUDE_DIRS "."
    REQUIRES esp_driver_gpio esp_timer)
