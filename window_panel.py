"""The window panel: a second card, along the bottom, for the window itself.

Pin (keep on top), click-through, background opacity, window opacity,
minimize and close. The two opacity buttons open a small slider next to
the panel; scrolling on them changes the opacity directly, and a
double-click puts it back to 100%.
"""

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from platform_support import shortcut_text
from shapes import squircle_path
from tool_panel import (
    ACTIVE_COLOR, BORDER_COLOR, BUTTON_RADIUS, EDGE_MARGIN, ICON_COLOR, PANEL_COLOR, ButtonPanel,
)

OPACITY_STEP = 0.05  # one scroll notch on an opacity button: 5%
MIN_WINDOW_OPACITY = 0.2  # the window never fades out completely
TRACK_COLOR = QColor("#48484A")  # the empty part of a slider
SLIDER_WIDTH = 220
SLIDER_HEIGHT = 64
SLIDER_PADDING = 14
SLIDER_GAP = 8  # between the window panel and a slider above it
KNOB_RADIUS = 7


# ---- Icons (20 x 20 grid, like the tool panel's) -----------------------------


def icon_pin():
    # A pushpin: a cap, a body that flares out, and the needle.
    path = QPainterPath()
    path.moveTo(7, 2)
    path.lineTo(13, 2)
    path.moveTo(8, 2)
    path.lineTo(8, 8)
    path.lineTo(5, 11.5)
    path.lineTo(15, 11.5)
    path.lineTo(12, 8)
    path.lineTo(12, 2)
    path.moveTo(10, 11.5)
    path.lineTo(10, 18)
    return path


def icon_click_through():
    # A mouse pointer that has gone through a (dashed) window.
    path = QPainterPath()
    # The window's outline, in dashes, left open where the pointer is.
    for x in (2, 5.5, 9, 12.5):
        path.moveTo(x, 2)
        path.lineTo(x + 1.5, 2)
    for y in (5.5, 9, 12.5):
        path.moveTo(2, y)
        path.lineTo(2, y + 1.5)
    path.moveTo(2, 2)
    path.lineTo(2, 3.5)
    path.moveTo(15, 2)
    path.lineTo(15, 3.5)
    path.moveTo(2, 15)
    path.lineTo(3.5, 15)
    # The pointer.
    path.moveTo(7, 7)
    path.lineTo(7, 18)
    path.lineTo(9.8, 15.4)
    path.lineTo(11.8, 19.5)
    path.lineTo(13.6, 18.6)
    path.lineTo(11.6, 14.6)
    path.lineTo(15.4, 14.6)
    path.closeSubpath()
    return path


def icon_background_opacity():
    # A square whose lower half is hatched: "the background, partly see-through".
    path = QPainterPath()
    path.addRect(QRectF(2, 2, 16, 16))
    path.moveTo(2, 18)
    path.lineTo(18, 2)
    path.moveTo(8, 18)
    path.lineTo(18, 8)
    path.moveTo(13, 18)
    path.lineTo(18, 13)
    return path


def icon_window_opacity():
    # Two overlapping squares: you can see one through the other.
    path = QPainterPath()
    path.addRect(QRectF(2, 2, 11, 11))
    path.addRect(QRectF(7, 7, 11, 11))
    return path


def icon_minimize():
    path = QPainterPath()
    path.moveTo(4, 14)
    path.lineTo(16, 14)
    return path


def icon_close():
    path = QPainterPath()
    path.moveTo(5, 5)
    path.lineTo(15, 15)
    path.moveTo(15, 5)
    path.lineTo(5, 15)
    return path


class OpacitySlider(QWidget):
    """A little card with a title, a percentage and a slider, next to the
    window panel. Click or drag on it, or scroll. Double-click: 100%.
    A click anywhere else, or Esc, closes it."""

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setting = None  # the Opacity setting this slider is showing
        self.owner_rect = None  # the button that opened us, in window coordinates
        self.setFixedSize(SLIDER_WIDTH, SLIDER_HEIGHT)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)

        canvas.opacity_changed.connect(self.update)  # changed by keys or scrolling
        self.hide()

    def open(self, setting, owner_rect, position):
        self.setting = setting
        self.owner_rect = owner_rect
        self.move(position)
        self.show()
        self.raise_()
        # Watch every click in the app, to close when one lands somewhere else.
        QApplication.instance().installEventFilter(self)

    def close_slider(self):
        self.hide()
        self.setting = None
        QApplication.instance().removeEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            point = event.globalPosition().toPoint()
            inside = self.rect().contains(self.mapFromGlobal(point))
            # Clicks on the button that opened us are the panel's business
            # (a second click closes, a double-click resets).
            on_owner = self.owner_rect.contains(self.window().mapFromGlobal(point))
            if not inside and not on_owner:
                self.close_slider()
        elif event.type() == QEvent.ShortcutOverride and event.key() == Qt.Key_Escape:
            # Before a key press, Qt asks "is this key a shortcut, or does a
            # widget want it?". Esc is also the window's shortcut for closing
            # the start panel; claiming it here means the key press comes
            # through to us instead.
            event.accept()
            return True
        elif event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.close_slider()
            return True  # used up: don't also close the start panel or cancel a crop
        return False

    # ---- Layout --------------------------------------------------------------

    def track(self):
        """The slider's line: where 0% (or the minimum) and 100% are."""
        y = SLIDER_HEIGHT - SLIDER_PADDING - KNOB_RADIUS
        return QPointF(SLIDER_PADDING + KNOB_RADIUS, y), QPointF(SLIDER_WIDTH - SLIDER_PADDING - KNOB_RADIUS, y)

    def value_at(self, x):
        start, end = self.track()
        fraction = max(0.0, min(1.0, (x - start.x()) / (end.x() - start.x())))
        lowest = self.setting.minimum
        return round((lowest + fraction * (1 - lowest)) * 100) / 100  # whole percents

    # ---- Mouse ---------------------------------------------------------------

    def mousePressEvent(self, event):
        event.accept()
        if event.button() == Qt.LeftButton and self.setting is not None:
            self.setting.set(self.value_at(event.position().x()))

    def mouseMoveEvent(self, event):
        event.accept()
        if event.buttons() & Qt.LeftButton and self.setting is not None:
            self.setting.set(self.value_at(event.position().x()))

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()
        if self.setting is not None:
            self.setting.set(1.0)

    def wheelEvent(self, event):
        event.accept()
        if self.setting is not None:
            self.setting.scroll(event.angleDelta().y() or event.angleDelta().x())

    # ---- Drawing -------------------------------------------------------------

    def paintEvent(self, event):
        if self.setting is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), BUTTON_RADIUS + 2))

        # Title on the left, percentage on the right.
        font = QFont(self.font())
        font.setPixelSize(13)
        painter.setFont(font)
        painter.setPen(ICON_COLOR)
        text_rect = QRectF(SLIDER_PADDING, SLIDER_PADDING - 2, SLIDER_WIDTH - SLIDER_PADDING * 2, 18)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.setting.title)
        painter.drawText(text_rect, Qt.AlignRight | Qt.AlignVCenter, f"{round(self.setting.get() * 100)}%")

        # The track: blue up to the knob, gray after it.
        start, end = self.track()
        lowest = self.setting.minimum
        fraction = (self.setting.get() - lowest) / (1 - lowest)
        knob = start + (end - start) * fraction
        pen = QPen(TRACK_COLOR, 4)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(start, end)
        pen.setColor(ACTIVE_COLOR)
        painter.setPen(pen)
        painter.drawLine(start, knob)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ICON_COLOR)
        painter.drawEllipse(knob, KNOB_RADIUS, KNOB_RADIUS)


class Opacity:
    """One opacity setting (background or window): how to read and change it."""

    def __init__(self, title, get, set, minimum):
        self.title = title
        self.get = get
        self._set = set
        self.minimum = minimum

    def set(self, value):
        self._set(max(self.minimum, min(1.0, value)))

    def scroll(self, angle):
        # One wheel notch is 120 "units"; touchpads send smaller amounts.
        self.set(round((self.get() + angle / 120 * OPACITY_STEP) * 100) / 100)

    def percent(self):
        return round(self.get() * 100)


class WindowPanel(ButtonPanel):
    """A row of buttons, centred along the bottom edge of the canvas."""

    def __init__(self, canvas, window):
        self.background = Opacity("Background", lambda: canvas.background_opacity,
                                  canvas.set_background_opacity, 0.0)
        self.whole_window = Opacity("Window", lambda: canvas.window_opacity,
                                    canvas.set_window_opacity, MIN_WINDOW_OPACITY)
        never = lambda: False
        always = lambda: True
        groups = [
            [
                (icon_pin(), "Keep on top of other windows", window.toggle_pin, always,
                 lambda: window.pinned),
                (icon_click_through(),
                 "Click-through: clicks go to the window behind refboard.\n"
                 "Switch back to refboard (Alt+Tab, the taskbar or the tray icon) to turn it off.",
                 window.toggle_click_through, always, lambda: window.click_through),
                (icon_background_opacity(),
                 lambda: self.opacity_tip(self.background),
                 self.open_background_slider, always, lambda: canvas.background_opacity < 1),
                (icon_window_opacity(),
                 lambda: self.opacity_tip(self.whole_window),
                 self.open_window_slider, always, lambda: canvas.window_opacity < 1),
            ],
            [
                (icon_minimize(), "Minimize", window.showMinimized, always, never),
                (icon_close(), f"Close  ({shortcut_text('Ctrl+W')})", window.close, always, never),
            ],
        ]
        super().__init__(canvas, groups, horizontal=True)
        self.slider = OpacitySlider(canvas)
        canvas.opacity_changed.connect(self.update)
        canvas.installEventFilter(self)  # to stay in place when the window is resized
        self.place()

    def place(self):
        """Bottom edge, with a margin; horizontally centred."""
        self.move((self.canvas.width() - self.width()) // 2,
                  self.canvas.height() - self.height() - EDGE_MARGIN)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.place()
            self.slider.close_slider()  # it would be in the wrong place now
        return False  # only looking; the canvas still handles the event

    def opacity_tip(self, setting):
        return (f"{setting.title} opacity: {setting.percent()}%\n"
                f"Click for a slider, scroll to change, double-click for 100%.\n"
                f"Reset both: {shortcut_text('Ctrl+Shift+O')}")

    def open_background_slider(self):
        self.toggle_slider(self.background, self.open_background_slider)

    def open_window_slider(self):
        self.toggle_slider(self.whole_window, self.open_window_slider)

    def toggle_slider(self, setting, action):
        """Open the slider for `setting` above its button, or close it if
        it's already open for it."""
        if self.slider.isVisible() and self.slider.setting is setting:
            self.slider.close_slider()
            return
        rect = self.button_rect(action).translated(self.pos())  # in canvas coordinates
        x = round(rect.center().x() - SLIDER_WIDTH / 2)
        y = self.y() - SLIDER_GAP - SLIDER_HEIGHT
        # Stay inside the canvas, even in a small window.
        x = max(0, min(x, self.canvas.width() - SLIDER_WIDTH))
        y = max(0, min(y, self.canvas.height() - SLIDER_HEIGHT))
        # The slider needs to know where its button is in the window, to
        # leave clicks on it alone.
        owner_rect = rect.toRect()
        owner_rect.moveTopLeft(self.canvas.mapTo(self.window(), owner_rect.topLeft()))
        self.slider.open(setting, owner_rect, QPoint(x, y))

    def setting_at(self, pos):
        """The opacity setting whose button is at `pos`, if any."""
        _key, button = self.button_at(pos)
        if button is None:
            return None
        return {self.open_background_slider: self.background,
                self.open_window_slider: self.whole_window}.get(button[2])

    def wheelEvent(self, event):
        event.accept()
        setting = self.setting_at(event.position())
        if setting is not None:
            setting.scroll(event.angleDelta().y() or event.angleDelta().x())

    def mouseDoubleClickEvent(self, event):
        setting = self.setting_at(event.position())
        if setting is None:
            super().mouseDoubleClickEvent(event)
            return
        event.accept()
        setting.set(1.0)
        self.slider.close_slider()
