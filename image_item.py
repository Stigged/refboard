"""One image on the canvas, plus the handles you use to scale and rotate it."""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QStyle

# Look and feel of the selection box and its corner handles.
ACCENT_COLOR = QColor("#0A84FF")  # Apple "systemBlue" (dark mode)
HANDLE_FILL = QColor("#FFFFFF")
HANDLE_SIZE = 8  # corner squares, in screen pixels (stay the same size at any zoom)
HANDLE_GRAB = 8  # how close (screen pixels) the mouse must be to grab a corner
ROTATE_GRAB = 28  # just outside a corner, up to this distance, you rotate instead


class ImageItem(QGraphicsPixmapItem):
    """A picture that can be selected, moved, scaled and rotated.

    Scaling and rotating always happen around the image's centre, so the
    image stays where it is while it grows, shrinks or turns.
    """

    def __init__(self, image):
        super().__init__(QPixmap.fromImage(image))
        self.setTransformationMode(Qt.SmoothTransformation)
        # Let the user click to select it and drag it around.
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        # Scale and rotate around the middle instead of the top-left corner.
        self.setTransformOriginPoint(self.local_rect().center())

    def local_rect(self):
        """The image's rectangle in its own units (before scaling/rotating)."""
        return QRectF(self.pixmap().rect())

    def corners(self):
        """The four corners, in the image's own units."""
        r = self.local_rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def center_in_scene(self):
        """Where the image's middle is on the canvas."""
        return self.mapToScene(self.local_rect().center())

    def paint(self, painter, option, widget=None):
        # Hide Qt's default dotted selection box; we draw a nicer one below.
        option.state &= ~QStyle.State_Selected
        super().paint(painter, option, widget)
        if not self.isSelected():
            return

        # The painter is zoomed and scaled along with the image. Work out how
        # big one screen pixel is in image units, so handles stay a fixed size.
        t = painter.worldTransform()
        pixel = 1 / math.hypot(t.m11(), t.m12())

        outline = QPen(ACCENT_COLOR, 1.5)
        outline.setCosmetic(True)  # line width in screen pixels, not image units
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.local_rect())

        painter.setBrush(HANDLE_FILL)
        half = HANDLE_SIZE / 2 * pixel
        for corner in self.corners():
            painter.drawRect(QRectF(corner - QPointF(half, half), corner + QPointF(half, half)))
