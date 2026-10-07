"""The canvas: an endless dark surface you can pan around and zoom into."""

import math

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView

from image_item import HANDLE_GRAB, ROTATE_GRAB, ImageItem

# Look and feel. Tweak these freely.
# Colors borrowed from Apple's dark-mode system grays.
BACKGROUND_COLOR = QColor("#1C1C1E")  # Apple "systemGray6"
DOT_COLOR = QColor("#3A3A3C")  # Apple "systemGray4"
DOT_SPACING = 50  # distance between grid dots, in canvas units
ZOOM_STEP = 1.15  # how much one scroll-wheel notch zooms
MIN_ZOOM = 0.02
MAX_ZOOM = 50
STACK_OFFSET = 30  # when adding several images at once, shift each one by this much
IMAGE_SCALE_STEP = 1.1  # how much one Ctrl+scroll notch scales selected images
MIN_IMAGE_SCALE = 0.01
ROTATE_STEP = 15  # degrees per Alt+scroll notch, and the Shift snapping angle

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

        # Report mouse movement even with no button held, so the cursor can
        # change when hovering over a scale/rotate handle.
        self.viewport().setMouseTracking(True)

        self._pan_last_pos = None  # set while the middle mouse button is held
        self._handle_drag = None  # set while dragging a scale/rotate handle
        self.centerOn(0, 0)

    def zoom_level(self):
        """1.0 means 100%. m11 is the horizontal scale factor of the view."""
        return self.transform().m11()

    # ---- Adding images -----------------------------------------------------

    def add_image(self, image, center):
        """Put a QImage on the canvas, centred on `center` (in canvas units)."""
        item = ImageItem(image)
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

    # ---- Mouse wheel: zoom the board, or scale/rotate selected images ------

    def wheelEvent(self, event):
        # One wheel notch is 120 "units". Touchpads send smaller amounts,
        # which gives smooth zooming for free.
        # Qt turns Alt+scroll into sideways scrolling, so read whichever axis moved.
        notches = (event.angleDelta().y() or event.angleDelta().x()) / 120
        selected = self.scene().selectedItems()
        ctrl = bool(event.modifiers() & Qt.ControlModifier)
        alt = bool(event.modifiers() & Qt.AltModifier)

        if selected and ctrl:
            for item in selected:
                item.setScale(max(MIN_IMAGE_SCALE, item.scale() * IMAGE_SCALE_STEP**notches))
            return
        if selected and alt:
            for item in selected:
                item.setRotation((item.rotation() + ROTATE_STEP * notches) % 360)
            return

        target = self.zoom_level() * ZOOM_STEP**notches
        target = max(MIN_ZOOM, min(MAX_ZOOM, target))
        factor = target / self.zoom_level()
        self.scale(factor, factor)

    # ---- Handles: find which one (if any) is under the mouse ---------------

    def handle_at(self, pos):
        """Is `pos` (window pixels) on a corner handle of a selected image?

        Returns (item, "scale") or (item, "rotate"), or None if not.
        On the corner = scale. Just outside the corner = rotate.
        """
        scene_pos = self.mapToScene(pos)
        for item in self.scene().selectedItems():
            for corner in item.corners():
                corner_on_screen = self.mapFromScene(item.mapToScene(corner))
                distance = math.dist((pos.x(), pos.y()), (corner_on_screen.x(), corner_on_screen.y()))
                if distance <= HANDLE_GRAB:
                    return item, "scale"
                outside = not item.contains(item.mapFromScene(scene_pos))
                if distance <= ROTATE_GRAB and outside:
                    return item, "rotate"
        return None

    def angle_from_center(self, item, scene_pos):
        """Angle (degrees) of the line from the image's centre to `scene_pos`."""
        d = scene_pos - item.center_in_scene()
        return math.degrees(math.atan2(d.y(), d.x()))

    def distance_from_center(self, item, scene_pos):
        d = scene_pos - item.center_in_scene()
        return math.hypot(d.x(), d.y())

    # ---- Mouse buttons: middle = pan, left = Qt's select/move + our handles

    def mousePressEvent(self, event):
        pos = event.position().toPoint()

        if event.button() == Qt.MiddleButton:
            self._pan_last_pos = pos
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.LeftButton:
            hit = self.handle_at(pos)
            if hit is not None:
                item, mode = hit
                scene_pos = self.mapToScene(pos)
                # Remember how things were at the start of the drag; every
                # mouse move then compares against this starting point.
                self._handle_drag = {
                    "item": item,
                    "mode": mode,
                    "start_scale": item.scale(),
                    "start_distance": max(1e-6, self.distance_from_center(item, scene_pos)),
                    "start_rotation": item.rotation(),
                    "start_angle": self.angle_from_center(item, scene_pos),
                }
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self._pan_last_pos is not None:
            delta: QPoint = pos - self._pan_last_pos
            self._pan_last_pos = pos
            # Panning = moving the hidden scrollbars the opposite way.
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            return

        if self._handle_drag is not None:
            drag = self._handle_drag
            item = drag["item"]
            scene_pos = self.mapToScene(pos)
            if drag["mode"] == "scale":
                # Twice as far from the centre as when you grabbed it = twice as big.
                ratio = self.distance_from_center(item, scene_pos) / drag["start_distance"]
                item.setScale(max(MIN_IMAGE_SCALE, drag["start_scale"] * ratio))
            else:
                # Turn by however much the mouse has swung around the centre.
                turned = self.angle_from_center(item, scene_pos) - drag["start_angle"]
                angle = drag["start_rotation"] + turned
                if event.modifiers() & Qt.ShiftModifier:
                    angle = round(angle / ROTATE_STEP) * ROTATE_STEP
                item.setRotation(angle % 360)
            return

        # No button held: show a hint cursor when hovering over a handle.
        if event.buttons() == Qt.NoButton:
            hit = self.handle_at(pos)
            if hit is None:
                self.viewport().unsetCursor()
            elif hit[1] == "scale":
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.CrossCursor)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_last_pos is not None:
            self._pan_last_pos = None
            self.viewport().unsetCursor()
            return
        if event.button() == Qt.LeftButton and self._handle_drag is not None:
            self._handle_drag = None
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


        