"""The application window: one card per bulb, plus the shared header."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .model import (
    Bulb,
    ColorMode,
    LEVEL_MAX,
    LEVEL_MIN,
    clamp,
    float_to_matter_hs,
    kelvin_to_mireds,
    kelvin_to_rgb,
    matter_hs_to_float,
    mireds_to_kelvin,
)
from .widgets import ColorWheel, GradientSlider

CONFIG_PATH = Path.home() / ".config" / "kajplats" / "config.json"

#: (label, kelvin) — clamped to each bulb's physical range before sending.
WHITE_PRESETS = [
    ("Candle", 2000),
    ("Warm", 2700),
    ("Soft", 3000),
    ("Neutral", 4000),
    ("Cool", 5000),
    ("Daylight", 6500),
]

#: (label, hue 0..1, saturation 0..1)
COLOR_PRESETS = [
    ("Red", 0.00, 1.00),
    ("Orange", 0.07, 1.00),
    ("Amber", 0.12, 0.85),
    ("Green", 0.33, 1.00),
    ("Teal", 0.47, 0.90),
    ("Cyan", 0.50, 1.00),
    ("Blue", 0.62, 1.00),
    ("Violet", 0.75, 0.90),
    ("Magenta", 0.83, 1.00),
    ("Pink", 0.92, 0.50),
]


def load_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save_config(config: dict) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2))
    except OSError:
        pass  # a missing config file is not worth interrupting the user for


class Swatch(QPushButton):
    """A round, single-colour preset button."""

    def __init__(self, color: QColor, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QPushButton {{
                background: {color.name()};
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 13px;
            }}
            QPushButton:hover {{ border: 2px solid rgba(255,255,255,0.75); }}
            QPushButton:pressed {{ border: 2px solid #ffffff; }}
            """
        )


class BulbCard(QFrame):
    """Controls for a single bulb.

    The card is a pure view: it emits intent and is told what to display. All
    fan-out (the "link bulbs" behaviour) happens in the window above it.
    """

    powerRequested = Signal(object, bool)        # Bulb, on
    colorRequested = Signal(object, int, int)    # Bulb, hue, saturation
    levelRequested = Signal(object, int)         # Bulb, level
    temperatureRequested = Signal(object, int)   # Bulb, mireds
    renamed = Signal(object, str)                # Bulb, new name

    def __init__(self, bulb: Bulb, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bulb = bulb
        self.setObjectName("bulbCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        layout.addLayout(self._build_header())
        layout.addLayout(self._build_mode_row())

        self._wheel = ColorWheel()
        self._wheel.picked.connect(self._on_wheel)
        layout.addWidget(self._wheel, 1)

        self._swatches = self._build_swatches()
        layout.addWidget(self._swatches)

        self._brightness_label = QLabel()
        self._brightness_label.setObjectName("sliderLabel")
        layout.addWidget(self._brightness_label)
        self._brightness = GradientSlider(LEVEL_MIN, LEVEL_MAX, bulb.level)
        self._brightness.valueChanged.connect(self._on_brightness)
        layout.addWidget(self._brightness)

        self._temperature_label = QLabel()
        self._temperature_label.setObjectName("sliderLabel")
        layout.addWidget(self._temperature_label)
        self._temperature = GradientSlider(bulb.ct_min, bulb.ct_max, bulb.mireds)
        self._temperature.set_stops(self._temperature_stops(bulb))
        self._temperature.valueChanged.connect(self._on_temperature)
        layout.addWidget(self._temperature)

        self.update_from(bulb)

    # -- construction ------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self._name = QLineEdit(self._bulb.name)
        self._name.setObjectName("bulbName")
        self._name.setToolTip("Rename this bulb (stored locally)")
        self._name.editingFinished.connect(
            lambda: self.renamed.emit(self._bulb, self._name.text().strip())
        )
        row.addWidget(self._name, 1)

        self._power = QPushButton("On")
        self._power.setObjectName("powerButton")
        self._power.setCheckable(True)
        self._power.setFixedWidth(68)
        self._power.setCursor(Qt.CursorShape.PointingHandCursor)
        self._power.clicked.connect(
            lambda checked: self.powerRequested.emit(self._bulb, checked)
        )
        row.addWidget(self._power)
        return row

    def _build_mode_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)
        self._mode_group = QButtonGroup(self)
        self._color_mode_button = QPushButton("Colour")
        self._white_mode_button = QPushButton("White")
        for index, button in enumerate(
            (self._color_mode_button, self._white_mode_button)
        ):
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setObjectName(
                "segmentLeft" if index == 0 else "segmentRight"
            )
            self._mode_group.addButton(button, index)
            row.addWidget(button)
        # Picking a mode re-sends that mode's current value, which is what
        # actually flips the bulb's ColorMode attribute.
        self._color_mode_button.clicked.connect(
            lambda: self._on_wheel(*self._wheel.hs())
        )
        self._white_mode_button.clicked.connect(
            lambda: self._on_temperature(self._temperature.value())
        )
        self._status = QLabel()
        self._status.setObjectName("cardStatus")
        row.addSpacing(10)
        row.addWidget(self._status, 1, Qt.AlignmentFlag.AlignRight)
        return row

    def _build_swatches(self) -> QWidget:
        container = QWidget()
        container.setObjectName("swatches")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # Kept as widgets rather than bare layouts so the colour row can be
        # hidden wholesale on white-spectrum-only bulbs.
        self._color_swatches = QWidget()
        colors = QHBoxLayout(self._color_swatches)
        colors.setContentsMargins(0, 0, 0, 0)
        colors.setSpacing(6)
        for label, hue, saturation in COLOR_PRESETS:
            color = QColor.fromHsvF(hue, saturation, 1.0)
            swatch = Swatch(color, label)
            swatch.clicked.connect(
                lambda _=False, h=hue, s=saturation: self._apply_color_preset(h, s)
            )
            colors.addWidget(swatch)
        colors.addStretch(1)
        outer.addWidget(self._color_swatches)

        self._white_swatches = QWidget()
        whites = QHBoxLayout(self._white_swatches)
        whites.setContentsMargins(0, 0, 0, 0)
        whites.setSpacing(6)
        for label, kelvin in WHITE_PRESETS:
            color = QColor(*kelvin_to_rgb(kelvin))
            swatch = Swatch(color, f"{label} · {kelvin} K")
            swatch.clicked.connect(
                lambda _=False, k=kelvin: self._apply_white_preset(k)
            )
            whites.addWidget(swatch)
        whites.addStretch(1)
        outer.addWidget(self._white_swatches)
        return container

    # -- intent ------------------------------------------------------------

    def _on_wheel(self, hue: float, saturation: float) -> None:
        matter_hue, matter_saturation = float_to_matter_hs(hue, saturation)
        self._color_mode_button.setChecked(True)
        self._wheel.set_marker_active(True)
        self._refresh_brightness_ramp(hue, saturation)
        self.colorRequested.emit(self._bulb, matter_hue, matter_saturation)

    def _on_brightness(self, level: int) -> None:
        self._brightness_label.setText(self._brightness_text(level))
        self._wheel.set_brightness(level / LEVEL_MAX)
        self.levelRequested.emit(self._bulb, level)

    def _on_temperature(self, mireds: int) -> None:
        self._white_mode_button.setChecked(True)
        self._temperature_label.setText(self._temperature_text(mireds))
        self.temperatureRequested.emit(self._bulb, mireds)

    def _apply_color_preset(self, hue: float, saturation: float) -> None:
        self._wheel.set_hs(hue, saturation)
        self._on_wheel(hue, saturation)

    def _apply_white_preset(self, kelvin: int) -> None:
        mireds = int(
            clamp(kelvin_to_mireds(kelvin), self._bulb.ct_min, self._bulb.ct_max)
        )
        self._temperature.set_value(mireds)
        self._on_temperature(mireds)

    # -- display -----------------------------------------------------------

    def update_from(self, bulb: Bulb) -> None:
        """Adopt backend state, leaving any control the user is dragging alone."""
        self._bulb = bulb

        if not self._name.hasFocus():
            self._name.setText(bulb.name)

        self._power.setChecked(bulb.on)
        self._power.setText("On" if bulb.on else "Off")

        # A white-spectrum bulb has no hue at all: showing a colour wheel it
        # cannot obey would be a lie, so the colour controls come out entirely
        # rather than sitting there greyed.
        self._wheel.setVisible(bulb.supports_color)
        self._color_swatches.setVisible(bulb.supports_color)
        self._color_mode_button.setVisible(bulb.supports_color)
        self._white_mode_button.setVisible(bulb.supports_color)

        hue, saturation = matter_hs_to_float(bulb.hue, bulb.saturation)
        self._wheel.set_hs(hue, saturation)
        self._wheel.set_brightness(bulb.level / LEVEL_MAX)
        self._wheel.set_dimmed(not bulb.on or not bulb.online)
        self._wheel.set_marker_active(bulb.mode is ColorMode.HS)
        self._wheel.setEnabled(bulb.online and bulb.supports_color)

        self._brightness.set_value(bulb.level)
        self._brightness.set_dimmed(not bulb.on or not bulb.online)
        self._brightness_label.setText(self._brightness_text(bulb.level))
        self._refresh_brightness_ramp(hue, saturation)

        self._temperature.set_range(bulb.ct_min, bulb.ct_max)
        self._temperature.set_stops(self._temperature_stops(bulb))
        self._temperature.set_value(bulb.mireds)
        self._temperature.set_dimmed(not bulb.on or not bulb.online)
        self._temperature.setEnabled(bulb.online and bulb.supports_ct)
        self._temperature_label.setText(self._temperature_text(bulb.mireds))

        if bulb.supports_color:
            button = (
                self._white_mode_button
                if bulb.mode is ColorMode.CT
                else self._color_mode_button
            )
            if not button.isChecked():
                button.setChecked(True)

        if not bulb.online:
            self._status.setText("unreachable")
        elif not bulb.supports_color:
            self._status.setText(f"white spectrum · node {bulb.node_id}")
        else:
            self._status.setText(f"node {bulb.node_id}")
        self.setProperty("offline", not bulb.online)
        self.style().unpolish(self)
        self.style().polish(self)

    def _refresh_brightness_ramp(self, hue: float, saturation: float) -> None:
        """Tint the brightness groove with the colour currently selected."""
        if self._bulb.mode is ColorMode.CT:
            tint = QColor(*kelvin_to_rgb(mireds_to_kelvin(self._temperature.value())))
        else:
            tint = QColor.fromHsvF(clamp(hue, 0, 1), clamp(saturation, 0, 1), 1.0)
        self._brightness.set_stops(
            [(0.0, QColor(14, 15, 20)), (0.12, QColor(40, 40, 46)), (1.0, tint)]
        )

    def _temperature_stops(self, bulb: Bulb) -> list[tuple[float, QColor]]:
        # The slider runs in mireds, which increase as the light gets warmer,
        # so the ramp is built from the cool end leftwards.
        stops: list[tuple[float, QColor]] = []
        span = max(bulb.ct_max - bulb.ct_min, 1)
        for step in range(9):
            fraction = step / 8.0
            mireds = bulb.ct_min + fraction * span
            stops.append((fraction, QColor(*kelvin_to_rgb(mireds_to_kelvin(mireds)))))
        return stops

    def _brightness_text(self, level: int) -> str:
        percent = round((level - LEVEL_MIN) / (LEVEL_MAX - LEVEL_MIN) * 100)
        return f"Brightness · {percent}%"

    def _temperature_text(self, mireds: int) -> str:
        return f"White · {mireds_to_kelvin(mireds)} K"


class CommissionDialog(QDialog):
    """Collects the pairing code (and optionally a Thread dataset)."""

    def __init__(self, thread_set: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add a KAJPLATS bulb")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        intro = QLabel(
            "Factory-reset the bulb (six quick power cycles), then enter the "
            "pairing code from the bulb or its packaging.\n\n"
            "Pairing takes 1–3 minutes: Bluetooth handshake, then the bulb "
            "joins the Thread mesh. Leave this window open until it finishes — "
            "closing it cancels the pairing."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("MT:... or the 11-digit manual code")
        form.addRow("Pairing code", self.code)

        self.dataset = QLineEdit()
        self.dataset.setPlaceholderText(
            "hex operational dataset from your border router"
        )
        form.addRow("Thread dataset", self.dataset)
        layout.addLayout(form)

        if thread_set:
            note = QLabel(
                "The server already holds a Thread dataset — leave that field "
                "blank to keep it."
            )
        else:
            note = QLabel(
                "No Thread dataset is stored yet. Commissioning will fail "
                "without one: run <code>ot-ctl dataset active -x</code> on your "
                "border router and paste the result."
            )
        note.setWordWrap(True)
        note.setObjectName("dialogNote")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QWidget):
    """Top-level window: header, the bulb cards, and the status line."""

    def __init__(self, controller, backend_label: str) -> None:
        super().__init__()
        self._controller = controller
        self._backend_label = backend_label
        self._config = load_config()
        self._cards: dict[str, BulbCard] = {}
        self._bulbs: dict[str, Bulb] = {}

        self.setWindowTitle("KAJPLATS")
        self.resize(900, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(14)
        root.addLayout(self._build_header())

        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(14)
        root.addLayout(self._cards_row, 1)

        self._placeholder = QLabel("Looking for bulbs…")
        self._placeholder.setObjectName("placeholder")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._cards_row.addWidget(self._placeholder)

        self._status = QLabel("")
        self._status.setObjectName("statusLine")
        root.addWidget(self._status)

        controller.stateChanged.connect(self._on_state)
        controller.errorRaised.connect(self._on_error)
        controller.noticePosted.connect(self._on_notice)

    # -- construction ------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        title = QLabel("KAJPLATS")
        title.setObjectName("title")
        row.addWidget(title)

        self._pill = QLabel("connecting…")
        self._pill.setObjectName("pill")
        row.addWidget(self._pill)
        row.addStretch(1)

        self._link = QCheckBox("Link bulbs")
        self._link.setToolTip("Apply every change to all bulbs at once")
        self._link.setChecked(bool(self._config.get("link", False)))
        self._link.toggled.connect(self._on_link_toggled)
        row.addWidget(self._link)

        all_on = QPushButton("All on")
        all_on.clicked.connect(lambda: self._set_all_power(True))
        row.addWidget(all_on)

        all_off = QPushButton("All off")
        all_off.clicked.connect(lambda: self._set_all_power(False))
        row.addWidget(all_off)

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._controller.refresh)
        row.addWidget(refresh)

        self._add_button = QPushButton("Add bulb…")
        self._add_button.clicked.connect(self._open_commission_dialog)
        row.addWidget(self._add_button)
        return row

    # -- state in ----------------------------------------------------------

    def _on_state(self, bulbs: list, connected: bool, detail: str) -> None:
        names = self._config.setdefault("names", {})
        resolved = []
        for bulb in bulbs:
            override = names.get(bulb.key)
            resolved.append(bulb.with_changes(name=override) if override else bulb)

        self._bulbs = {bulb.key: bulb for bulb in resolved}
        self._sync_cards(resolved)

        self._pill.setText("connected" if connected else "offline")
        self._pill.setProperty("state", "ok" if connected else "bad")
        self._pill.style().unpolish(self._pill)
        self._pill.style().polish(self._pill)

        pieces = [self._backend_label]
        if detail:
            pieces.append(detail)
        pieces.append(f"{len(resolved)} bulb{'s' if len(resolved) != 1 else ''}")
        self._status.setText("  ·  ".join(pieces))

    def _sync_cards(self, bulbs: list) -> None:
        keys = {bulb.key for bulb in bulbs}

        for key in list(self._cards):
            if key not in keys:
                card = self._cards.pop(key)
                self._cards_row.removeWidget(card)
                card.deleteLater()

        for bulb in bulbs:
            card = self._cards.get(bulb.key)
            if card is None:
                card = BulbCard(bulb)
                card.powerRequested.connect(self._handle_power)
                card.colorRequested.connect(self._handle_color)
                card.levelRequested.connect(self._handle_level)
                card.temperatureRequested.connect(self._handle_temperature)
                card.renamed.connect(self._handle_rename)
                self._cards[bulb.key] = card
                self._cards_row.addWidget(card)
            else:
                card.update_from(bulb)

        has_bulbs = bool(bulbs)
        self._placeholder.setVisible(not has_bulbs)
        if not has_bulbs:
            self._placeholder.setText(
                "No bulbs on the fabric yet.\n"
                "Use “Add bulb…” once a Thread border router is running."
            )

    def _on_error(self, message: str) -> None:
        self._status.setText(message)

    def _on_notice(self, message: str) -> None:
        self._status.setText(message)

    # -- intent out --------------------------------------------------------

    def _targets(self, origin: Bulb) -> list[Bulb]:
        """The bulbs a change should reach, honouring the link toggle."""
        if not self._link.isChecked():
            return [self._bulbs.get(origin.key, origin)]
        return list(self._bulbs.values()) or [origin]

    def _handle_power(self, bulb: Bulb, on: bool) -> None:
        for target in self._targets(bulb):
            self._controller.set_power(target, on)

    def _handle_color(self, bulb: Bulb, hue: int, saturation: int) -> None:
        for target in self._targets(bulb):
            self._controller.set_hs(target, hue, saturation)

    def _handle_level(self, bulb: Bulb, level: int) -> None:
        for target in self._targets(bulb):
            self._controller.set_level(target, level)

    def _handle_temperature(self, bulb: Bulb, mireds: int) -> None:
        for target in self._targets(bulb):
            clamped = int(clamp(mireds, target.ct_min, target.ct_max))
            self._controller.set_ct(target, clamped)

    def _handle_rename(self, bulb: Bulb, name: str) -> None:
        names = self._config.setdefault("names", {})
        if name and name != bulb.name:
            names[bulb.key] = name
        elif not name:
            names.pop(bulb.key, None)
        save_config(self._config)
        existing = self._bulbs.get(bulb.key)
        if existing is not None:
            self._bulbs[bulb.key] = existing.with_changes(
                name=name or existing.product or f"Light {bulb.node_id}"
            )

    def _set_all_power(self, on: bool) -> None:
        for bulb in self._bulbs.values():
            self._controller.set_power(bulb, on)

    def _on_link_toggled(self, checked: bool) -> None:
        self._config["link"] = checked
        save_config(self._config)

    def _open_commission_dialog(self) -> None:
        backend = self._controller.backend
        if not getattr(backend, "can_commission", False):
            QMessageBox.information(
                self,
                "Commissioning unavailable",
                "This backend cannot commission bulbs.\n\n"
                "Start matterjs-server with a Bluetooth adapter "
                "(--bluetooth-adapter 0) and a Thread border router on the "
                "network, then reconnect.",
            )
            return

        info = getattr(backend, "server_info", {})
        dialog = CommissionDialog(bool(info.get("thread_credentials_set")), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        dataset = dialog.dataset.text().strip()
        if dataset:
            self._controller.set_thread_dataset(dataset)
        code = dialog.code.text().strip()
        if code:
            self._status.setText(
                "Commissioning… this takes 1–3 minutes. Keep this window open "
                "and leave the bulb powered."
            )
            self._controller.commission(code)

    # -- Qt ----------------------------------------------------------------

    def closeEvent(self, event) -> None:
        save_config(self._config)
        self._controller.shutdown()
        super().closeEvent(event)
