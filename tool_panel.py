"""The tool panel: a slim vertical card on the left edge with icon buttons.

The icons are drawn with lines in code (no image files), on a 20 x 20 grid,
so they match the rest of the look and stay sharp at any screen scaling.

ButtonPanel is the card itself (layout, hovering, clicking, drawing). The
tool panel and the window panel (window_panel.py) each fill one with
their own buttons.
"""

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QToolTip, QWidget

from platform_support import delete_shortcut_text, shortcut_text
from shapes import squircle_path

# Colors (same Apple dark-mode grays as the start panel).
PANEL_COLOR = QColor("#2C2C2E")  # one shade lighter than the canvas
BORDER_COLOR = QColor("#3A3A3C")
HOVER_COLOR = QColor("#3A3A3C")
ACTIVE_COLOR = QColor("#0A84FF")  # a tool that's switched on, like crop mode
ICON_COLOR = QColor("#E5E5EA")
DISABLED_ICON_COLOR = QColor("#5A5A5E")  # nothing to do right now

# Sizes, in pixels.
EDGE_MARGIN = 16  # distance from the window's edge
PADDING = 8  # inside the panel, around the buttons
BUTTON_SIZE = 36
BUTTON_GAP = 4
GROUP_GAP = 13  # extra room between groups, with a thin line in it
PANEL_RADIUS = 16
BUTTON_RADIUS = 10
ICON_SIZE = 20  # the icons are drawn on a 20 x 20 grid
ICON_LINE_WIDTH = 1.6


# ---- Icons -------------------------------------------------------------------
# Each function returns a QPainterPath on the 20 x 20 grid.


def icon_crop():
    path = QPainterPath()
    path.moveTo(5, 1)
    path.lineTo(5, 15)
    path.lineTo(19, 15)
    path.moveTo(1, 5)
    path.lineTo(15, 5)
    path.lineTo(15, 19)
    return path


def icon_straighten():
    # A compass: a circle with an arrow pointing north.
    path = QPainterPath()
    path.addEllipse(QRectF(2, 2, 16, 16))
    path.moveTo(10, 14.5)
    path.lineTo(10, 5.5)
    path.moveTo(7, 8.5)
    path.lineTo(10, 5.5)
    path.lineTo(13, 8.5)
    return path


def icon_flip_horizontal():
    # Two triangles, mirror images of each other, either side of a dotted line.
    path = QPainterPath()
    path.moveTo(8, 4)
    path.lineTo(8, 16)
    path.lineTo(2, 16)
    path.closeSubpath()
    path.moveTo(12, 4)
    path.lineTo(12, 16)
    path.lineTo(18, 16)
    path.closeSubpath()
    for y in range(2, 20, 4):
        path.moveTo(10, y)
        path.lineTo(10, y + 1)
    return path


def icon_flip_vertical():
    # The same, turned a quarter turn.
    turn = QTransform().translate(ICON_SIZE, 0).rotate(90)
    return turn.map(icon_flip_horizontal())


def icon_grayscale():
    # A circle, half of it shaded with lines: "color off".
    path = QPainterPath()
    path.addEllipse(QRectF(2, 2, 16, 16))
    path.moveTo(10, 2)
    path.lineTo(10, 18)
    for y in (5.5, 8.5, 11.5, 14.5):
        # Stop each line just inside the circle (radius 8, centre 10, 10).
        x = 10 + math.sqrt(8**2 - (y - 10) ** 2) - 1.5
        path.moveTo(10, y)
        path.lineTo(x, y)
    return path


def icon_delete():
    # A bin: lid, handle and a slightly narrowing body.
    path = QPainterPath()
    path.moveTo(3, 5)
    path.lineTo(17, 5)
    path.moveTo(8, 5)
    path.lineTo(8, 2.5)
    path.lineTo(12, 2.5)
    path.lineTo(12, 5)
    path.moveTo(5, 5)
    path.lineTo(6, 18)
    path.lineTo(14, 18)
    path.lineTo(15, 5)
    return path


def icon_undo():
    # An arrowhead pointing left, and a line that curls back round.
    path = QPainterPath()
    path.moveTo(7, 4)
    path.lineTo(3, 8)
    path.lineTo(7, 12)
    path.moveTo(3, 8)
    path.lineTo(12, 8)
    # Half a circle, from its top (90 degrees) clockwise to its bottom.
    path.arcTo(QRectF(7.5, 8, 9, 9), 90, -180)
    path.lineTo(8, 17)
    return path


def icon_redo():
    # Undo, mirrored left-to-right: flip x (scale by -1), then shift it back
    # into the 20 x 20 box.
    mirror = QTransform().translate(ICON_SIZE, 0).scale(-1, 1)
    return mirror.map(icon_undo())


def icon_fit():
    # Four corner brackets pointing outwards: "show everything".
    path = QPainterPath()
    for (x, y, dx, dy) in [(2, 2, 1, 1), (18, 2, -1, 1), (18, 18, -1, -1), (2, 18, 1, -1)]:
        path.moveTo(x, y + dy * 5)
        path.lineTo(x, y)
        path.lineTo(x + dx * 5, y)
    return path


def icon_bring_to_front():
    # An arrow pointing up at a line: "all the way to the top".
    path = QPainterPath()
    path.moveTo(4, 3)
    path.lineTo(16, 3)
    path.moveTo(10, 17)
    path.lineTo(10, 7)
    path.moveTo(6, 11)
    path.lineTo(10, 7)
    path.lineTo(14, 11)
    return path


def icon_send_to_back():
    # The same, flipped upside down.
    flip = QTransform().translate(0, ICON_SIZE).scale(1, -1)
    return flip.map(icon_bring_to_front())


class ButtonPanel(QWidget):
    """A floating card with a row or column of icon buttons, on top of the canvas.

    `groups` is a list of button groups (a thin line separates them). Each
    button is: (icon, tooltip, what to call, "can it do anything now?",
    "is it switched on?"). The tooltip can also be a function that returns
    the text, for tooltips that change.
    """

    def __init__(self, canvas, groups, horizontal=False):
        super().__init__(canvas)
        self.canvas = canvas
        self.groups = groups
        self.horizontal = horizontal  # buttons side by side instead of stacked
        self.hovered = None  # (group, number) of the button under the mouse

        # A soft shadow underneath, so the panel looks like it floats.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 130))
        self.setGraphicsEffect(shadow)

        self.setMouseTracking(True)
        button_count = sum(len(group) for group in self.groups)
        length = (
            PADDING * 2
            + button_count * BUTTON_SIZE
            + (button_count - len(self.groups)) * BUTTON_GAP
            + (len(self.groups) - 1) * GROUP_GAP
        )
        thickness = PADDING * 2 + BUTTON_SIZE
        if horizontal:
            self.setFixedSize(length, thickness)
        else:
            self.setFixedSize(thickness, length)

    # ---- Layout --------------------------------------------------------------

    def buttons(self):
        """Every button with its rectangle: yields ((group, number), rect, button)."""
        along = PADDING  # how far along the panel we are (down, or to the right)
        for g, group in enumerate(self.groups):
            if g > 0:
                along += GROUP_GAP - BUTTON_GAP
            for n, button in enumerate(group):
                if self.horizontal:
                    rect = QRectF(along, PADDING, BUTTON_SIZE, BUTTON_SIZE)
                else:
                    rect = QRectF(PADDING, along, BUTTON_SIZE, BUTTON_SIZE)
                yield (g, n), rect, button
                along += BUTTON_SIZE + BUTTON_GAP

    def button_at(self, pos):
        for key, rect, button in self.buttons():
            if rect.contains(pos):
                return key, button
        return None, None

    def button_rect(self, action):
        """Where the button that calls `action` is, in panel coordinates."""
        for _key, rect, button in self.buttons():
            if button[2] == action:
                return rect
        return None

    # ---- Mouse ---------------------------------------------------------------

    def mouseMoveEvent(self, event):
        key, _button = self.button_at(event.position())
        if key != self.hovered:
            self.hovered = key
            self.update()

    def leaveEvent(self, event):
        self.hovered = None
        self.update()

    def mousePressEvent(self, event):
        event.accept()  # never let clicks fall through to the canvas
        _key, button = self.button_at(event.position())
        if event.button() == Qt.LeftButton and button is not None:
            _icon, _tip, action, enabled, _active = button
            if enabled():
                action()
                self.update()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)  # a fast second click counts as another click

    def wheelEvent(self, event):
        event.accept()

    def event(self, event):
        # Qt sends a ToolTip event when the mouse rests on us for a moment.
        if event.type() == QEvent.ToolTip:
            _key, button = self.button_at(QPointF(event.pos()))
            if button is not None:
                tip = button[1]() if callable(button[1]) else button[1]
                QToolTip.showText(event.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    # ---- Drawing -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS))

        previous_group = 0
        for (g, n), rect, (icon, _tip, _action, enabled, active) in self.buttons():
            # A thin divider line between groups.
            if g != previous_group:
                painter.setPen(QPen(BORDER_COLOR, 1))
                if self.horizontal:
                    x = rect.left() - GROUP_GAP / 2 + BUTTON_GAP / 2
                    painter.drawLine(QPointF(x, PADDING + 6), QPointF(x, PADDING + BUTTON_SIZE - 6))
                else:
                    y = rect.top() - GROUP_GAP / 2 + BUTTON_GAP / 2
                    painter.drawLine(QPointF(PADDING + 6, y), QPointF(PADDING + BUTTON_SIZE - 6, y))
                previous_group = g

            is_enabled, is_active = enabled(), active()
            hovered = (g, n) == self.hovered and is_enabled

            # Squircle background: blue when switched on, gray when hovered.
            if is_active or hovered:
                painter.setPen(Qt.NoPen)
                painter.setBrush(ACTIVE_COLOR if is_active else HOVER_COLOR)
                painter.drawPath(squircle_path(rect, BUTTON_RADIUS))

            # The icon, centred in the button.
            painter.save()
            offset = (BUTTON_SIZE - ICON_SIZE) / 2
            painter.translate(rect.left() + offset, rect.top() + offset)
            pen = QPen(ICON_COLOR if is_enabled else DISABLED_ICON_COLOR, ICON_LINE_WIDTH)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(icon)
            painter.restore()


class ToolPanel(ButtonPanel):
    """Floats on the left edge of its parent (the canvas), vertically centred."""

    def __init__(self, canvas):
        # The buttons, in groups. Each one is:
        # (icon, tooltip, what to call, "can it do anything now?", "is it switched on?")
        never = lambda: False
        has_images = lambda: bool(canvas.selected_images())
        has_selection = lambda: bool(canvas.scene().selectedItems())
        groups = [
            [
                (icon_crop(), "Crop  (C)", canvas.toggle_crop,
                 lambda: has_images() or canvas.crop_item is not None,
                 lambda: canvas.crop_item is not None),
                (icon_straighten(), "Straighten (north up)", canvas.straighten_selected,
                 canvas.any_selected_rotated, never),
                (icon_flip_horizontal(), "Flip horizontally  (H)", canvas.flip_horizontal, has_images, never),
                (icon_flip_vertical(), "Flip vertically  (V)", canvas.flip_vertical, has_images, never),
                (icon_grayscale(), "Black and white  (G)", canvas.toggle_grayscale,
                 has_images, canvas.selected_all_gray),
                (icon_delete(), f"Delete  ({delete_shortcut_text()})", canvas.delete_selected, has_selection, never),
            ],
            [
                (icon_bring_to_front(), f"Bring to front  ({shortcut_text('Ctrl+]')}   one step: ])",
                 canvas.bring_to_front, has_selection, never),
                (icon_send_to_back(), f"Send to back  ({shortcut_text('Ctrl+[')}   one step: [)",
                 canvas.send_to_back, has_selection, never),
            ],
            [
                (icon_undo(), f"Undo  ({shortcut_text('Ctrl+Z')})", canvas.undo, canvas.can_undo, never),
                (icon_redo(), f"Redo  ({shortcut_text('Ctrl+Shift+Z')})", canvas.redo, canvas.can_redo, never),
            ],
            [
                (icon_fit(), "Fit all  (F)", canvas.fit_all, lambda: bool(canvas.board_items()), never),
            ],
        ]
        super().__init__(canvas, groups)

        # Repaint whenever something happens that could dim or light up a button.
        canvas.scene().selectionChanged.connect(self.update)
        canvas.changed.connect(self.update)
        canvas.crop_mode_changed.connect(self.update)

        canvas.installEventFilter(self)
        self.place()

    def place(self):
        """Left edge, with a margin; vertically centred."""
        self.move(EDGE_MARGIN, (self.canvas.height() - self.height()) // 2)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.place()
        return False  # only looking; the canvas still handles the event
