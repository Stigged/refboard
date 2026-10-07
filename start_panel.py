"""The start panel: a small floating window with your recent boards.

For now it only shows four placeholder tiles; opening boards comes later.
"""

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# Colors: Apple dark-mode "elevated" grays.
PANEL_COLOR = QColor("#2C2C2E")
BORDER_COLOR = QColor("#3A3A3C")
TILE_COLOR = QColor("#3A3A3C")
TITLE_COLOR = QColor("#E5E5EA")
LABEL_COLOR = QColor("#8E8E93")

# Sizes, in pixels.
PANEL_FRACTION = 0.66  # the panel takes up 66% of the window's width and height
MIN_PANEL_WIDTH = 360  # ...but never smaller than this (unless the window is)
MIN_PANEL_HEIGHT = 300
PADDING = 24  # space between the panel's edge and its contents
TITLE_HEIGHT = 40
LABEL_HEIGHT = 30  # room for the board name under each tile
GAP = 16  # space between tiles
PANEL_RADIUS = 28
TILE_RADIUS = 14

# Corner shape. 2 would be an ordinary circle-like corner; higher numbers are
# "squarer" with a smoother transition. 5 is close to Apple's icon corners.
CORNER_SMOOTHNESS = 5
CORNER_STEPS = 24  # how many little line pieces make up one corner


def squircle_path(rect, radius):
    """A rectangle with G2-continuous (curvature-continuous) rounded corners.

    Each corner is a quarter of a superellipse, |x|^n + |y|^n = 1. Unlike a
    circle arc, its curvature fades to zero where it meets the straight
    edge, so there's no visible "kink" where the corner begins.
    """
    r = min(radius, rect.width() / 2, rect.height() / 2)
    # Centre of each corner's curve, clockwise from top-right.
    centres = [
        QPointF(rect.right() - r, rect.top() + r),
        QPointF(rect.right() - r, rect.bottom() - r),
        QPointF(rect.left() + r, rect.bottom() - r),
        QPointF(rect.left() + r, rect.top() + r),
    ]
    power = 2 / CORNER_SMOOTHNESS
    path = QPainterPath()
    for corner, centre in enumerate(centres):
        for step in range(CORNER_STEPS + 1):
            t = step / CORNER_STEPS * (math.pi / 2)
            # One point on the top-right quarter of a superellipse...
            x, y = math.sin(t) ** power, -(math.cos(t) ** power)
            # ...turned 90 degrees once per corner, to fit that corner.
            for _ in range(corner):
                x, y = -y, x
            point = centre + QPointF(x * r, y * r)
            if corner == 0 and step == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)  # the straight edges come for free between corners
    path.closeSubpath()
    return path


class StartPanel(QWidget):
    """Floats in the middle of its parent (the canvas), sized as a share of it."""

    def __init__(self, parent):
        super().__init__(parent)

        # A soft shadow underneath, so the panel looks like it floats.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        # Watch the parent's events, so we notice when it's resized.
        parent.installEventFilter(self)
        self.fit_to_parent()

    def fit_to_parent(self):
        """Resize to PANEL_FRACTION of the parent, and centre on it."""
        parent = self.parentWidget()
        width = max(MIN_PANEL_WIDTH, round(parent.width() * PANEL_FRACTION))
        height = max(MIN_PANEL_HEIGHT, round(parent.height() * PANEL_FRACTION))
        # In a really small window, don't stick out past its edges.
        width = min(width, parent.width())
        height = min(height, parent.height())
        self.setGeometry((parent.width() - width) // 2, (parent.height() - height) // 2, width, height)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.fit_to_parent()
        return False  # False = "I only looked"; the parent still handles the event

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # The panel itself. Shrunk by half a pixel so the 1px border lands
        # exactly on whole pixels and looks crisp.
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS))

        # Title.
        font = QFont(self.font())
        font.setPointSizeF(13)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(TITLE_COLOR)
        title_area = QRectF(PADDING, PADDING, self.width() - PADDING * 2, TITLE_HEIGHT)
        painter.drawText(title_area, Qt.AlignLeft | Qt.AlignTop, "Recent boards")

        # Four tiles in a 2 x 2 grid. They share whatever room is left after
        # the padding, title, labels and gaps, so they grow with the panel.
        tile_width = (self.width() - PADDING * 2 - GAP) / 2
        tile_height = (self.height() - PADDING * 2 - TITLE_HEIGHT - LABEL_HEIGHT * 2 - GAP) / 2
        font.setPointSizeF(10)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        for number in range(4):
            row, column = divmod(number, 2)  # 0 -> (0,0), 1 -> (0,1), 2 -> (1,0), 3 -> (1,1)
            x = PADDING + column * (tile_width + GAP)
            y = PADDING + TITLE_HEIGHT + row * (tile_height + LABEL_HEIGHT + GAP)

            painter.setPen(Qt.NoPen)
            painter.setBrush(TILE_COLOR)
            painter.drawPath(squircle_path(QRectF(x, y, tile_width, tile_height), TILE_RADIUS))

            painter.setPen(LABEL_COLOR)
            label_area = QRectF(x + 2, y + tile_height, tile_width, LABEL_HEIGHT)
            painter.drawText(label_area, Qt.AlignLeft | Qt.AlignVCenter, f"Board {number + 1}")
