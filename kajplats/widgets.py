"""Custom Qt widgets: the hue/saturation wheel and the gradient sliders.

Qt's stock QSlider cannot show a colour ramp in its groove, and there is no
built-in colour wheel, so both are drawn here. Both widgets are purely about
presentation and input — they hold a value, emit changes, and know nothing
about Matter.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from .model import clamp


class ColorWheel(QWidget):
    """Hue around the rim, saturation from centre to edge.

    Emits `picked` continuously while dragging so the bulb follows the finger,
    and `committed` on release for anything that should only happen once.
    """

    picked = Signal(float, float)  # hue 0..1, saturation 0..1
    committed = Signal()

    MARKER_RADIUS = 9.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hue = 0.0
        self._saturation = 0.0
        self._brightness = 1.0
        self._enabled_look = True
        self._marker_active = True
        self._dragging = False
        self.setMinimumSize(170, 170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)

    # -- value -------------------------------------------------------------

    def hs(self) -> tuple[float, float]:
        return self._hue, self._saturation

    def set_hs(self, hue: float, saturation: float) -> None:
        """Move the marker without emitting — used to show backend state."""
        if self._dragging:
            return  # never fight the user's finger
        self._hue = clamp(hue, 0.0, 1.0)
        self._saturation = clamp(saturation, 0.0, 1.0)
        self.update()

    def set_brightness(self, value: float) -> None:
        """Dim the whole wheel to echo the bulb's brightness."""
        self._brightness = clamp(value, 0.0, 1.0)
        self.update()

    def set_dimmed(self, dimmed: bool) -> None:
        """Grey the wheel out when the bulb is off or unreachable."""
        self._enabled_look = not dimmed
        self.update()

    def set_marker_active(self, active: bool) -> None:
        """Fade the marker when hue/saturation is not what drives the bulb.

        In colour-temperature mode the wheel still works as an input, but the
        stored hue is not what the bulb is emitting, so showing a confident
        marker there would be a lie.
        """
        self._marker_active = active
        self.update()

    # -- geometry ----------------------------------------------------------

    def _disc(self) -> QRectF:
        side = min(self.width(), self.height()) - 2 * self.MARKER_RADIUS
        side = max(side, 10.0)
        return QRectF(
            (self.width() - side) / 2.0, (self.height() - side) / 2.0, side, side
        )

    def _hs_at(self, pos: QPoint) -> tuple[float, float]:
        disc = self._disc()
        centre = disc.center()
        dx = pos.x() - centre.x()
        # Screen y grows downwards; flip it so hue runs anticlockwise like the
        # conical gradient that paints it.
        dy = centre.y() - pos.y()
        radius = disc.width() / 2.0
        angle = math.degrees(math.atan2(dy, dx)) % 360.0
        distance = math.hypot(dx, dy)
        return angle / 360.0, clamp(distance / radius, 0.0, 1.0)

    def _marker_pos(self) -> QPointF:
        disc = self._disc()
        centre = disc.center()
        radius = disc.width() / 2.0
        angle = math.radians(self._hue * 360.0)
        return QPointF(
            centre.x() + math.cos(angle) * self._saturation * radius,
            centre.y() - math.sin(angle) * self._saturation * radius,
        )

    # -- input -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self._emit_at(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._emit_at(event.position().toPoint())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self.committed.emit()

    def keyPressEvent(self, event) -> None:
        step = 0.02 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 0.08
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._hue = (self._hue + step) % 1.0
        elif key == Qt.Key.Key_Right:
            self._hue = (self._hue - step) % 1.0
        elif key == Qt.Key.Key_Up:
            self._saturation = clamp(self._saturation + step, 0.0, 1.0)
        elif key == Qt.Key.Key_Down:
            self._saturation = clamp(self._saturation - step, 0.0, 1.0)
        else:
            super().keyPressEvent(event)
            return
        self.update()
        self.picked.emit(self._hue, self._saturation)
        self.committed.emit()

    def _emit_at(self, pos: QPoint) -> None:
        self._hue, self._saturation = self._hs_at(pos)
        self.update()
        self.picked.emit(self._hue, self._saturation)

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        disc = self._disc()

        # Hue: a conical sweep. Qt interpolates linearly between stops, so the
        # ring needs enough of them that the primaries stay true.
        hue_gradient = QConicalGradient(disc.center(), 0.0)
        for step in range(0, 361, 10):
            hue_gradient.setColorAt(
                min(step / 360.0, 1.0), QColor.fromHsvF(step / 360.0 % 1.0, 1.0, 1.0)
            )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(hue_gradient))
        painter.drawEllipse(disc)

        # Saturation: white in the middle fading out to the saturated rim.
        white = QRadialGradient(disc.center(), disc.width() / 2.0)
        white.setColorAt(0.0, QColor(255, 255, 255, 255))
        white.setColorAt(0.55, QColor(255, 255, 255, 110))
        white.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(white))
        painter.drawEllipse(disc)

        # Brightness, and the off/offline state, as a black veil.
        veil = (1.0 - self._brightness) * 0.72
        if not self._enabled_look:
            veil = max(veil, 0.78)
        if veil > 0.0:
            painter.setBrush(QColor(8, 10, 14, int(veil * 255)))
            painter.drawEllipse(disc)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 28), 1.0))
        painter.drawEllipse(disc)

        # Marker: a white ring with a dark outline so it reads on any hue.
        marker = self._marker_pos()
        alpha = 255 if self._marker_active else 90
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0, 160 if self._marker_active else 70), 3.0))
        painter.drawEllipse(marker, self.MARKER_RADIUS, self.MARKER_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, alpha), 2.0))
        painter.drawEllipse(marker, self.MARKER_RADIUS, self.MARKER_RADIUS)

        if self.hasFocus():
            painter.setPen(QPen(QColor(120, 170, 255, 190), 2.0))
            painter.drawEllipse(disc.adjusted(-3, -3, 3, 3))


class GradientSlider(QWidget):
    """A horizontal slider whose groove is a colour ramp.

    Used for brightness and for colour temperature, so the control itself
    previews what moving it will do.
    """

    valueChanged = Signal(int)
    committed = Signal()

    GROOVE_HEIGHT = 20.0
    HANDLE_RADIUS = 11.0

    def __init__(
        self,
        minimum: int,
        maximum: int,
        value: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._min = minimum
        self._max = max(maximum, minimum + 1)
        self._value = value if value is not None else minimum
        self._stops: list[tuple[float, QColor]] = [
            (0.0, QColor(20, 20, 20)),
            (1.0, QColor(255, 255, 255)),
        ]
        self._dragging = False
        self._dimmed = False
        self.setMinimumHeight(int(self.HANDLE_RADIUS * 2 + 6))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # -- value -------------------------------------------------------------

    def value(self) -> int:
        return self._value

    def set_value(self, value: int, *, emit: bool = False) -> None:
        clamped = int(clamp(value, self._min, self._max))
        if clamped == self._value:
            return
        if self._dragging and not emit:
            return
        self._value = clamped
        self.update()
        if emit:
            self.valueChanged.emit(clamped)

    def set_range(self, minimum: int, maximum: int) -> None:
        self._min = minimum
        self._max = max(maximum, minimum + 1)
        self._value = int(clamp(self._value, self._min, self._max))
        self.update()

    def set_stops(self, stops: list[tuple[float, QColor]]) -> None:
        self._stops = stops
        self.update()

    def set_dimmed(self, dimmed: bool) -> None:
        self._dimmed = dimmed
        self.update()

    # -- geometry ----------------------------------------------------------

    def _groove(self) -> QRectF:
        inset = self.HANDLE_RADIUS
        return QRectF(
            inset,
            (self.height() - self.GROOVE_HEIGHT) / 2.0,
            max(self.width() - 2 * inset, 1.0),
            self.GROOVE_HEIGHT,
        )

    def _fraction(self) -> float:
        return (self._value - self._min) / float(self._max - self._min)

    def _value_at(self, x: float) -> int:
        groove = self._groove()
        fraction = clamp((x - groove.left()) / groove.width(), 0.0, 1.0)
        return int(round(self._min + fraction * (self._max - self._min)))

    # -- input -------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = True
        self.set_value(self._value_at(event.position().x()), emit=True)

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self.set_value(self._value_at(event.position().x()), emit=True)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._dragging = False
        self.committed.emit()

    def wheelEvent(self, event) -> None:
        step = max(1, (self._max - self._min) // 40)
        delta = step if event.angleDelta().y() > 0 else -step
        self.set_value(self._value + delta, emit=True)
        self.committed.emit()

    def keyPressEvent(self, event) -> None:
        span = self._max - self._min
        small = max(1, span // 100)
        large = max(1, span // 10)
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Down):
            self.set_value(self._value - small, emit=True)
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_Up):
            self.set_value(self._value + small, emit=True)
        elif key == Qt.Key.Key_PageDown:
            self.set_value(self._value - large, emit=True)
        elif key == Qt.Key.Key_PageUp:
            self.set_value(self._value + large, emit=True)
        elif key == Qt.Key.Key_Home:
            self.set_value(self._min, emit=True)
        elif key == Qt.Key.Key_End:
            self.set_value(self._max, emit=True)
        else:
            super().keyPressEvent(event)
            return
        self.committed.emit()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        groove = self._groove()
        radius = groove.height() / 2.0

        gradient = QLinearGradient(groove.topLeft(), groove.topRight())
        for position, color in self._stops:
            gradient.setColorAt(position, color)

        path = QPainterPath()
        path.addRoundedRect(groove, radius, radius)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)

        if self._dimmed:
            painter.setBrush(QColor(8, 10, 14, 170))
            painter.drawPath(path)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        painter.drawPath(path)

        centre = QPointF(
            groove.left() + self._fraction() * groove.width(), groove.center().y()
        )
        painter.setBrush(QColor(255, 255, 255))
        painter.setPen(QPen(QColor(0, 0, 0, 120), 1.5))
        painter.drawEllipse(centre, self.HANDLE_RADIUS, self.HANDLE_RADIUS)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(120, 170, 255, 200), 2.0))
            painter.drawEllipse(centre, self.HANDLE_RADIUS + 3, self.HANDLE_RADIUS + 3)
