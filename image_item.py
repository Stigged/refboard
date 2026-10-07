"""One image on the canvas, plus the handles you use to scale, rotate and crop it."""

import math

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QStyle

# Look and feel of the selection box and its corner handles.
ACCENT_COLOR = QColor("#0A84FF")  # Apple "systemBlue" (dark mode)
HANDLE_FILL = QColor("#FFFFFF")
HANDLE_SIZE = 8  # corner squares, in screen pixels (stay the same size at any zoom)
HANDLE_GRAB = 8  # how close (screen pixels) the mouse must be to grab a corner
ROTATE_GRAB = 28  # just outside a corner, up to this distance, you rotate instead

# Crop mode.
CROP_GHOST_OPACITY = 0.25  # how visible the cut-off parts are while cropping
CROP_BRACKET_LENGTH = 18  # corner brackets, in screen pixels
CROP_BAR_LENGTH = 24  # bars in the middle of each edge, in screen pixels
CROP_LINE_WIDTH = 3
MIN_CROP_SIZE = 8  # an image can't be cropped smaller than this, in image pixels


class ImageItem(QGraphicsPixmapItem):
    """A picture that can be selected, moved, scaled, rotated and cropped.

    Scaling and rotating always happen around the middle of the visible
    (cropped) part, so the image stays where it is while it changes.

    Cropping never throws pixels away: we keep the full picture and only
    show the part inside `self.crop`. The item's own coordinates are always
    the full picture's pixel coordinates, so (0, 0) is the full picture's
    top-left corner even when that corner is cropped off.
    """

    def __init__(self, image, data=None, extension="png"):
        """`data` is the original file's bytes, if the image came from a file.

        We keep them so saving a board stores the image exactly as it was
        (a JPG stays a small JPG) instead of re-encoding it.
        """
        super().__init__(QPixmap.fromImage(image))
        self.full_pixmap = self.pixmap()
        self.crop = self.full_pixmap.rect()  # the visible part, in full-picture pixels
        self.cropping = False  # True while in crop mode (shows the ghost and brackets)
        self.data = data
        self.extension = extension
        self.setTransformationMode(Qt.SmoothTransformation)
        # Let the user click to select it and drag it around.
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        # Scale and rotate around the middle instead of the top-left corner.
        self.setTransformOriginPoint(self.local_rect().center())

    def file_data(self):
        """The image as file bytes plus a file extension, ready for saving."""
        if self.data is None:
            # Pasted images have no original file, so turn them into a PNG once.
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            self.full_pixmap.save(buffer, "PNG")
            self.data = bytes(buffer.data())
            self.extension = "png"
        return self.data, self.extension

    # ---- Cropping ----------------------------------------------------------

    def set_crop(self, rect):
        """Show only `rect` (a QRect in full-picture pixels) of the image."""
        rect = QRect(rect).intersected(self.full_pixmap.rect())
        if rect.width() < 1 or rect.height() < 1:
            return
        # Changing the crop moves the centre we rotate and scale around. To
        # stop the image jumping, remember where the picture's (0, 0) point
        # is on the canvas, and put it back there afterwards.
        before = self.mapToScene(QPointF(0, 0))
        self.prepareGeometryChange()  # tell Qt our size is about to change
        self.crop = rect
        self.setPixmap(self.full_pixmap.copy(rect))
        self.setOffset(rect.topLeft())  # draw the cut-out where it sat in the full picture
        self.setTransformOriginPoint(QRectF(rect).center())
        self.setPos(self.pos() + before - self.mapToScene(QPointF(0, 0)))

    def set_cropping(self, cropping):
        """Switch crop mode's visuals (ghost + brackets) on or off."""
        self.prepareGeometryChange()  # the ghost makes us bigger, see boundingRect
        self.cropping = cropping
        self.update()

    def boundingRect(self):
        # While cropping we also draw the ghost of the full picture, so tell
        # Qt our area includes all of it (otherwise it might not get redrawn).
        if self.cropping:
            return QRectF(self.full_pixmap.rect())
        return super().boundingRect()

    # ---- Geometry helpers --------------------------------------------------

    def local_rect(self):
        """The visible (cropped) part, in the item's own units (before scaling/rotating)."""
        return QRectF(self.crop)

    def corners(self):
        """The four corners of the visible part: top-left, top-right, bottom-right, bottom-left."""
        r = self.local_rect()
        return [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]

    def center_in_scene(self):
        """Where the image's middle is on the canvas."""
        return self.mapToScene(self.local_rect().center())

    # ---- Drawing -----------------------------------------------------------

    def paint(self, painter, option, widget=None):
        # Hide Qt's default dotted selection box; we draw a nicer one below.
        option.state &= ~QStyle.State_Selected

        if self.cropping:
            # The cut-off parts, faintly, so you can see what you could get back.
            painter.setOpacity(CROP_GHOST_OPACITY)
            painter.drawPixmap(QPointF(0, 0), self.full_pixmap)
            painter.setOpacity(1.0)

        super().paint(painter, option, widget)

        # The painter is zoomed and scaled along with the image. Work out how
        # big one screen pixel is in image units, so handles stay a fixed size.
        t = painter.worldTransform()
        pixel = 1 / math.hypot(t.m11(), t.m12())

        if self.cropping:
            self.paint_crop_handles(painter, pixel)
        elif self.isSelected():
            self.paint_selection(painter, pixel)

    def paint_selection(self, painter, pixel):
        outline = QPen(ACCENT_COLOR, 1.5)
        outline.setCosmetic(True)  # line width in screen pixels, not image units
        painter.setPen(outline)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.local_rect())

        painter.setBrush(HANDLE_FILL)
        half = HANDLE_SIZE / 2 * pixel
        for corner in self.corners():
            painter.drawRect(QRectF(corner - QPointF(half, half), corner + QPointF(half, half)))

    def paint_crop_handles(self, painter, pixel):
        r = self.local_rect()
        thin = QPen(HANDLE_FILL, 1)
        thin.setCosmetic(True)
        painter.setPen(thin)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)

        thick = QPen(HANDLE_FILL, CROP_LINE_WIDTH)
        thick.setCosmetic(True)
        thick.setCapStyle(Qt.FlatCap)
        painter.setPen(thick)
        # Keep brackets and bars from overlapping on very small crops.
        bracket = min(CROP_BRACKET_LENGTH * pixel, r.width() / 3, r.height() / 3)
        bar = min(CROP_BAR_LENGTH * pixel, r.width() / 3, r.height() / 3) / 2

        # An "L" in each corner: (corner point, which way to the inside x, y).
        for point, dx, dy in [
            (r.topLeft(), 1, 1),
            (r.topRight(), -1, 1),
            (r.bottomRight(), -1, -1),
            (r.bottomLeft(), 1, -1),
        ]:
            painter.drawLine(point, point + QPointF(dx * bracket, 0))
            painter.drawLine(point, point + QPointF(0, dy * bracket))

        # A short bar in the middle of each edge.
        c = r.center()
        painter.drawLine(QPointF(c.x() - bar, r.top()), QPointF(c.x() + bar, r.top()))
        painter.drawLine(QPointF(c.x() - bar, r.bottom()), QPointF(c.x() + bar, r.bottom()))
        painter.drawLine(QPointF(r.left(), c.y() - bar), QPointF(r.left(), c.y() + bar))
        painter.drawLine(QPointF(r.right(), c.y() - bar), QPointF(r.right(), c.y() + bar))
