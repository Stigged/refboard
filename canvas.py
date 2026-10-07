"""The canvas: an endless dark surface you can pan around and zoom into."""

import math

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)

# Look and feel. Tweak these freely.
# Colors borrowed from Apple's dark-mode system grays.
BACKGROUND_COLOR = QColor("#1C1C1E")  # Apple "systemGray6"
DOT_COLOR = QColor("#3A3A3C")  # Apple "systemGray4"
DOT_SPACING = 50  # distance between grid dots, in canvas units
ZOOM_STEP = 1.15  # how much one scroll-wheel notch zooms
MIN_ZOOM = 0.02
MAX_ZOOM = 50
STACK_OFFSET = 30  # when adding several images at once, shift each one by this much

# Qt needs the canvas to have *some* size. A million units in every
# direction is big enough that you'll never reach the edge.
CANVAS_SIZE = 1_000_000


class Canvas(QGraphicsView): 
    """A QGraphicsView is a window onto a QGraphicsScene.

    The scene holds the items (later: your images). The view decides which
    part of the scene you see and how zoomed in you are.
    """

    def __init__(self):
        super().__init__()

        scene = QGraphicsScene(self)
        scene.setSceneRect(-CANVAS_SIZE, -CANVAS_SIZE, CANVAS_SIZE * 2, CANVAS_SIZE * 2)
        self.setScene(scene)

        # Smooth edges and smooth image scaling.
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # No scrollbars or border: we pan with the mouse instead.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        # Zoom toward whatever is under the mouse, not the window centre.
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        # Redraw the whole window on every change, so the dot grid never glitches.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # Allow files and images to be dropped onto the canvas.
        self.setAcceptDrops(True)

        self._pan_last_pos = None  # set while the middle mouse button is held
        self.centerOn(0, 0)

    def zoom_level(self):
        """1.0 means 100%. m11 is the horizontal scale factor of the view."""
        return self.transform().m11()

    # ---- Adding images -----------------------------------------------------

    def add_image(self, image, center):
        """Put a QImage on the canvas, centred on `center` (in canvas units)."""
        item = QGraphicsPixmapItem(QPixmap.fromImage(image))
        item.setTransformationMode(Qt.SmoothTransformation)
        # Let the user click to select it and drag it around.
        item.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        item.setPos(center - QPointF(image.width() / 2, image.height() / 2))
        self.scene().addItem(item)

    def add_images_from_mime(self, mime, center):
        """Add every image found in dropped or pasted data. Returns True if any were added.

        "Mime data" is Qt's name for a package of data in several formats,
        used by both drag-and-drop and the clipboard.
        """
        images = []
        # Files, e.g. dragged in from Dolphin or copied in a file manager.
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    image = QImage(url.toLocalFile())
                    if not image.isNull():  # isNull means "not an image we can read"
                        images.append(image)
        # Raw image data, e.g. "Copy image" in a browser, or a screenshot.
        if not images and mime.hasImage():
            data = mime.imageData()
            if isinstance(data, QPixmap):
                data = data.toImage()
            if isinstance(data, QImage) and not data.isNull():
                images.append(data)

        for i, image in enumerate(images):
            offset = QPointF(i * STACK_OFFSET, i * STACK_OFFSET)
            self.add_image(image, center + offset)
        return bool(images)

    # ---- Drag and drop -----------------------------------------------------

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Must be overridden too, or Qt passes it to the scene, which refuses it.
        event.acceptProposedAction()

    def dropEvent(self, event):
        center = self.mapToScene(event.position().toPoint())
        if self.add_images_from_mime(event.mimeData(), center):
            event.acceptProposedAction()

    # ---- Paste (Ctrl+V) Delete ---------------------------------------------

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            # Paste where the mouse is, or in the middle if it's outside the window.
            mouse = self.viewport().mapFromGlobal(QCursor.pos())
            if not self.viewport().rect().contains(mouse):
                mouse = self.viewport().rect().center()
            self.add_images_from_mime(QApplication.clipboard().mimeData(), self.mapToScene(mouse))
            return

        if event.key() == Qt.Key_Delete:
            for item in self.scene().selectedItems():
                self.scene().removeItem(item)
            return
        super().keyPressEvent(event)

    # ---- Zooming -----------------------------------------------------------

    def wheelEvent(self, event):
        # One wheel notch is 120 "units". Touchpads send smaller amounts,
        # which gives smooth zooming for free.
        notches = event.angleDelta().y() / 120
        target = self.zoom_level() * ZOOM_STEP**notches
        target = max(MIN_ZOOM, min(MAX_ZOOM, target))
        factor = target / self.zoom_level()
        self.scale(factor, factor)

    # ---- Panning (hold middle mouse button and drag) -----------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_last_pos = event.position().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_last_pos is not None:
            pos = event.position().toPoint()
            delta: QPoint = pos - self._pan_last_pos
            self._pan_last_pos = pos
            # Panning = moving the hidden scrollbars the opposite way.
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_last_pos is not None:
            self._pan_last_pos = None
            self.unsetCursor()
            return
        super().mouseReleaseEvent(event)

    # ---- Background --------------------------------------------------------

    def drawBackground(self, painter, rect):
        """Paint the dark background with a faint dot grid.

        `rect` is the part of the canvas that needs painting, in canvas units.
        """
        painter.fillRect(rect, BACKGROUND_COLOR)

        # When zoomed far out the dots would crowd together, so spread them
        # out until they're at least 25 screen pixels apart.
        spacing = DOT_SPACING
        while spacing * self.zoom_level() < 25:
            spacing *= 2

        pen = QPen(DOT_COLOR, 2)
        pen.setCosmetic(True)  # 2 screen pixels wide, no matter the zoom
        painter.setPen(pen)

        # Start at the first grid line to the left of / above the visible area.
        first_x = math.floor(rect.left() / spacing) * spacing
        first_y = math.floor(rect.top() / spacing) * spacing
        points = []
        x = first_x
        while x < rect.right():
            y = first_y
            while y < rect.bottom():
                points.append(QPointF(x, y))
                y += spacing
            x += spacing
        painter.drawPoints(points)


        