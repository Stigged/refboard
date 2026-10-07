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

# Sizes, in pixels. The panel has one fixed size; the window's minimum size
# is built around it, so it always fits.
PANEL_WIDTH = 900
PANEL_HEIGHT = 555
WINDOW_MARGIN = 40  # minimum space between the panel and the window's edges
MIN_WINDOW_WIDTH = PANEL_WIDTH + WINDOW_MARGIN * 2
MIN_WINDOW_HEIGHT = PANEL_HEIGHT + WINDOW_MARGIN * 2
TILE_ASPECT = 16 / 10  # tiles are screenshot-shaped (width:height)
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
    """Floats in the middle of its parent (the canvas) and stays centred."""

    def __init__(self, parent):
        super().__init__(parent)

        # A soft shadow underneath, so the panel looks like it floats.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)
        # Watch the parent's events, so we notice when it's resized.
        parent.installEventFilter(self)
        self.center_in_parent()

    def center_in_parent(self):
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, (parent.height() - self.height()) // 2)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.center_in_parent()
        return False  # False = "I only looked"; the parent still handles the event

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # The panel itself. Shrunk by half a pixel so the 1px border lands
        # exactly on whole pixels and looks crisp.
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS))

        # Tile size: as big as the height allows while keeping 16:10, but no
        # wider than half the room. The fixed parts (padding, title, labels,
        # gaps) are subtracted first.
        room_width = (self.width() - PADDING * 2 - GAP) / 2
        room_height = (self.height() - PADDING * 2 - TITLE_HEIGHT - LABEL_HEIGHT * 2 - GAP) / 2
        tile_width = min(room_width, room_height * TILE_ASPECT)
        tile_height = tile_width / TILE_ASPECT
        # Centre the 2 x 2 grid sideways; any spare width goes to both sides.
        grid_width = tile_width * 2 + GAP
        left = (self.width() - grid_width) / 2

        # Title, lined up with the left edge of the tiles.
        font = QFont(self.font())
        font.setPointSizeF(13)
        font.setWeight(QFont.DemiBold)
        painter.setFont(font)
        painter.setPen(TITLE_COLOR)
        title_area = QRectF(left, PADDING, grid_width, TITLE_HEIGHT)
        painter.drawText(title_area, Qt.AlignLeft | Qt.AlignTop, "Recent boards")

        # Four tiles in a 2 x 2 grid.
        font.setPointSizeF(10)
        font.setWeight(QFont.Normal)
        painter.setFont(font)
        for number in range(4):
            row, column = divmod(number, 2)  # 0 -> (0,0), 1 -> (0,1), 2 -> (1,0), 3 -> (1,1)
            x = left + column * (tile_width + GAP)
            y = PADDING + TITLE_HEIGHT + row * (tile_height + LABEL_HEIGHT + GAP)

            painter.setPen(Qt.NoPen)
            painter.setBrush(TILE_COLOR)
            painter.drawPath(squircle_path(QRectF(x, y, tile_width, tile_height), TILE_RADIUS))

            painter.setPen(LABEL_COLOR)
            label_area = QRectF(x + 2, y + tile_height, tile_width, LABEL_HEIGHT)
            painter.drawText(label_area, Qt.AlignLeft | Qt.AlignVCenter, f"Board {number + 1}")
