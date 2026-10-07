"""What every thing on the board has in common: images and text notes.

BoardItem is a "mixin": a small class that adds methods to a Qt item class
without being an item itself. ImageItem and NoteItem each inherit from
BoardItem *and* from their own Qt class. Each of them must have a
local_rect() method; everything here is built on top of that.
"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

# Look and feel of the selection outline and its corner handles.
ACCENT_COLOR = QColor("#0A84FF")  # Apple "systemBlue" (dark mode)
HANDLE_FILL = QColor("#FFFFFF")
HANDLE_SIZE = 8  # corner squares, in screen pixels (stay the same size at any zoom)
HANDLE_GRAB = 8  # how close (screen pixels) the mouse must be to grab a corner
ROTATE_GRAB = 28  # just outside a corner, up to this distance, you rotate instead


def screen_pixel(painter):
    """How big one screen pixel is in the item's own units.

    The painter is zoomed, scaled and turned along with the item, so a
    handle that should look 8 pixels wide must be drawn 8 * this big.
    """
    t = painter.worldTransform()
    return 1 / math.hypot(t.m11(), t.m12())


class BoardItem:
    """Shared by ImageItem and NoteItem."""

    def corners(self):
        """The four corners of the visible part: top-left, top-right, bottom-right, bottom-left."""
        r = self.local_rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def center_in_scene(self):
        """Where the item's middle is on the canvas."""
        return self.mapToScene(self.local_rect().center())

    def scene_rect(self):
        """The visible part on the canvas, as an upright rectangle.

        For a rotated item this is the smallest upright box around it.
        Used to line things up (arrange, snapping).
        """
        return self.mapToScene(self.local_rect()).boundingRect()

    def paint_selection(self, painter):
        """The blue outline with white corner squares."""
        pixel = screen_pixel(painter)
        outline = QPen(ACCENT_COLOR, 1.5)
        outline.setCosmetic(True)  # line width in screen pixels, not item units
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.local_rect())

        painter.setBrush(HANDLE_FILL)
        half = HANDLE_SIZE / 2 * pixel
        for corner in self.corners():
            painter.drawRect(QRectF(corner - QPointF(half, half), corner + QPointF(half, half)))
