"""One image on the canvas, plus the handles you use to scale, rotate and crop it."""

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGraphicsItem, QGraphicsPixmapItem, QStyle

from board_item import HANDLE_FILL, BoardItem, screen_pixel

# Crop mode.
CROP_GHOST_OPACITY = 0.25  # how visible the cut-off parts are while cropping
CROP_BRACKET_LENGTH = 18  # corner brackets, in screen pixels
CROP_BAR_LENGTH = 24  # bars in the middle of each edge, in screen pixels
CROP_LINE_WIDTH = 3
MIN_CROP_SIZE = 8  # an image can't be cropped smaller than this, in image pixels


def to_grayscale(image):
    """A black-and-white copy of a QImage. See-through parts stay see-through."""
    gray = image.convertToFormat(QImage.Format_Grayscale8)
    gray = gray.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    if image.hasAlphaChannel():
        # Grayscale8 has no see-through information, so copy it back from
        # the original: "DestinationIn" keeps the gray pixels only as much
        # as the original pixel was visible.
        painter = QPainter(gray)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, image)
        painter.end()
    return gray


class ImageItem(BoardItem, QGraphicsPixmapItem):
    """A picture that can be selected, moved, scaled, rotated, cropped,
    flipped and shown in black and white.

    Scaling and rotating always happen around the middle of the visible
    (cropped) part, so the image stays where it is while it changes.

    Cropping never throws pixels away: we keep the full picture and only
    show the part inside `self.crop`. The item's own coordinates are always
    the full picture's pixel coordinates, so (0, 0) is the full picture's
    top-left corner even when that corner is cropped off.

    Flipping and grayscale work on the pixels: `full_pixmap` is the full
    picture *as shown* (mirrored and/or gray), and the crop is measured on
    that. The untouched original stays in `source_pixmap`.
    """

    def __init__(self, image, data=None, extension="png"):
        """`image` is a QImage or QPixmap. `data` is the original file's bytes,
        if the image came from a file.

        We keep them so saving a board stores the image exactly as it was
        (a JPG stays a small JPG) instead of re-encoding it.
        """
        pixmap = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
        super().__init__(pixmap)
        self.source_pixmap = pixmap  # the picture as it came in
        self.full_pixmap = pixmap  # the full picture as shown (flipped / gray)
        self.flipped_h = False  # mirrored left-right
        self.flipped_v = False  # mirrored top-bottom
        self.grayscale = False
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
            self.source_pixmap.save(buffer, "PNG")
            self.data = bytes(buffer.data())
            self.extension = "png"
        return self.data, self.extension

    # ---- Undo, duplicate ---------------------------------------------------

    def state(self):
        """Everything undo needs to put this image back exactly as it is now."""
        return (
            QRect(self.crop), self.pos(), self.scale(), self.rotation(), self.zValue(),
            self.flipped_h, self.flipped_v, self.grayscale,
        )

    def set_state(self, state):
        crop, pos, scale, rotation, z, flipped_h, flipped_v, grayscale = state
        self.set_look(flipped_h, flipped_v, grayscale)  # first: the crop is measured on the result
        self.set_crop(crop)  # before setPos: set_crop nudges the position itself
        self.setPos(pos)
        self.setScale(scale)
        self.setRotation(rotation)
        self.setZValue(z)

    def clone(self):
        """A new, identical image (not on the board yet)."""
        data, extension = self.file_data()  # so both copies share the same file bytes
        copy = ImageItem(self.source_pixmap, data, extension)
        copy.set_state(self.state())
        return copy

    # ---- Flip and grayscale ------------------------------------------------

    def set_look(self, flipped_h, flipped_v, grayscale):
        """Rebuild the shown picture from the original, if anything changed."""
        if (flipped_h, flipped_v, grayscale) == (self.flipped_h, self.flipped_v, self.grayscale):
            return  # nothing to do (and rebuilding big pictures is slow)
        self.flipped_h, self.flipped_v, self.grayscale = flipped_h, flipped_v, grayscale

        image = self.source_pixmap.toImage()
        directions = Qt.Orientation(0)
        if flipped_h:
            directions |= Qt.Horizontal
        if flipped_v:
            directions |= Qt.Vertical
        if directions:
            image = image.flipped(directions)
        if grayscale:
            image = to_grayscale(image)
        self.full_pixmap = QPixmap.fromImage(image)
        self.setPixmap(self.full_pixmap.copy(self.crop))
        self.update()

    def set_grayscale(self, grayscale):
        self.set_look(self.flipped_h, self.flipped_v, grayscale)

    def flip(self, horizontal):
        """Mirror the image as you see it on screen, left-right or top-bottom.

        Three things change together:
        - the pixels are mirrored,
        - the crop is mirrored too, so the same part stays visible,
        - the rotation turns the other way (a picture tilted 10 degrees to
          the right is tilted 10 degrees to the left in a mirror).
        Then the image is moved back so its middle stays put.
        """
        center = self.center_in_scene()
        c, full = self.crop, self.full_pixmap.rect()
        if horizontal:
            crop = QRect(full.width() - c.x() - c.width(), c.y(), c.width(), c.height())
            self.set_look(not self.flipped_h, self.flipped_v, self.grayscale)
        else:
            crop = QRect(c.x(), full.height() - c.y() - c.height(), c.width(), c.height())
            self.set_look(self.flipped_h, not self.flipped_v, self.grayscale)
        self.set_crop(crop)
        self.setRotation(-self.rotation() % 360)
        self.setPos(self.pos() + center - self.center_in_scene())

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

    def local_rect(self):
        """The visible (cropped) part, in the item's own units (before scaling/rotating)."""
        return QRectF(self.crop)

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

        if self.cropping:
            self.paint_crop_handles(painter, screen_pixel(painter))
        elif self.isSelected():
            self.paint_selection(painter)

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
