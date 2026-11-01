"""Headless render + interaction check. Saves a PNG of the window.

Exercises the paths a human would: wait for the simulator to report bulbs,
drive the wheel and both sliders, click presets, toggle power and link, then
capture the result.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kajplats.backend import MockBackend  # noqa: E402
from kajplats.controller import Controller  # noqa: E402
from kajplats.theme import STYLESHEET  # noqa: E402
from kajplats import window as window_module  # noqa: E402
from kajplats.window import MainWindow  # noqa: E402

# Never touch the real ~/.config/kajplats while testing.
window_module.CONFIG_PATH = pathlib.Path(tempfile.mkdtemp()) / "config.json"

OUT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/kajplats.png"


def spin(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


app = QApplication(sys.argv[:1])
app.setStyleSheet(STYLESHEET)

controller = Controller(MockBackend(count=2))
window = MainWindow(controller, "simulator")
window.resize(900, 780)
window.show()
controller.start()

spin(600)
cards = list(window._cards.values())
assert len(cards) == 2, f"expected 2 cards, got {len(cards)}"
print("cards:", [c._bulb.name for c in cards])

first, second = cards

# Colour wheel: pick a saturated teal on the first bulb.
first._wheel.set_hs(0.47, 0.9)
first._on_wheel(0.47, 0.9)
spin(200)
assert window._bulbs[first._bulb.key].saturation > 200, "saturation did not apply"
print("after wheel:", window._bulbs[first._bulb.key])

# Brightness slider, including the clamp at the bottom of the range.
first._brightness.set_value(120, emit=True)
spin(200)
assert window._bulbs[first._bulb.key].level == 120
first._brightness.set_value(-50, emit=True)
spin(150)
assert window._bulbs[first._bulb.key].level == 1, "level should clamp to 1"
first._brightness.set_value(200, emit=True)
spin(200)

# White preset on the second bulb, then its temperature slider.
second._apply_white_preset(2000)
spin(200)
state = window._bulbs[second._bulb.key]
assert state.mode.value == "ct", state.mode
assert state.mireds == min(500, state.ct_max), state.mireds
print("after white preset:", state)

second._temperature.set_value(250, emit=True)
spin(200)
assert window._bulbs[second._bulb.key].mireds == 250

# Colour preset.
first._apply_color_preset(0.83, 1.0)
spin(200)

# Power toggles.
second._power.setChecked(False)
second._handle = second.powerRequested.emit(second._bulb, False)
spin(250)
assert window._bulbs[second._bulb.key].on is False, "power off did not apply"
print("after power off:", window._bulbs[second._bulb.key])

# Link mode: one change must reach both bulbs.
window._link.setChecked(True)
window._set_all_power(True)
spin(250)
first._apply_color_preset(0.07, 1.0)
spin(350)
hues = {k: b.hue for k, b in window._bulbs.items()}
print("linked hues:", hues)
assert len(set(hues.values())) == 1, f"link did not fan out: {hues}"

# Rename persistence path.
window._handle_rename(first._bulb, "Desk lamp")
spin(50)

window._link.setChecked(False)
second._apply_white_preset(2700)
spin(200)
first._brightness.set_value(230, emit=True)
spin(250)

window.grab().save(OUT)
print("saved", OUT)
controller.shutdown()
print("SMOKE OK")
