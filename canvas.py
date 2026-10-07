"""The canvas: an endless dark surface you can pan around and zoom into."""

import math
import time
from collections import deque

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView

from image_item import HANDLE_GRAB, MIN_CROP_SIZE, ROTATE_GRAB, ImageItem

# Look and feel. Tweak these freely.
# Colors borrowed from Apple's dark-mode system grays.
BACKGROUND_COLOR = QColor("#1C1C1E")  # Apple "systemGray6"
DOT_COLOR = QColor("#3A3A3C")  # Apple "systemGray4"
DOT_SPACING = 50  # distance between grid dots, in canvas units
ZOOM_STEP = 1.15  # how much one scroll-wheel notch zooms
MIN_ZOOM = 0.02
MAX_ZOOM = 50
PREVIEW_WIDTH = 640  # size of the little picture saved inside each board file
PREVIEW_HEIGHT = 400
STACK_OFFSET = 30  # when adding several images at once, shift each one by this much
IMAGE_SCALE_STEP = 1.1  # how much one Ctrl+scroll notch scales selected images
MIN_IMAGE_SCALE = 0.01
ROTATE_STEP = 15  # degrees per Alt+scroll notch, and the Shift snapping angle
FIT_MARGIN = 0.05  # "fit all" leaves this much room around the images (5%)
UNDO_LIMIT = 20  # how many steps Ctrl+Z can go back
WHEEL_UNDO_PAUSE = 0.6  # seconds; scroll notches closer together than this are one undo step

# Qt needs the canvas to have *some* size. A million units in every
# direction is big enough that you'll never reach the edge.
CANVAS_SIZE = 1_000_000

# Which crop edges each corner moves, in the order ImageItem.corners() gives them.
CORNER_EDGES = [{"left", "top"}, {"right", "top"}, {"right", "bottom"}, {"left", "bottom"}]
# Each side, as (name, first corner, second corner).
SIDES = [("top", 0, 1), ("right", 1, 2), ("bottom", 2, 3), ("left", 3, 0)]


def distance_to_segment(p, a, b):
    """Shortest distance from point p to the line piece from a to b."""
    ab, ap = b - a, p - a
    length_squared = ab.x() ** 2 + ab.y() ** 2
    # How far along a->b the closest point is: 0 = at a, 1 = at b.
    t = 0.0 if length_squared == 0 else (ap.x() * ab.x() + ap.y() * ab.y()) / length_squared
    t = max(0.0, min(1.0, t))
    closest = a + ab * t
    return math.hypot(p.x() - closest.x(), p.y() - closest.y())


class Canvas(QGraphicsView):
    """A QGraphicsView is a window onto a QGraphicsScene.

    The scene holds the items (later: your images). The view decides which
    part of the scene you see and how zoomed in you are.
    """

    # A signal is like a wire other parts of the program can connect to.
    # We "emit" it whenever the board changes, so the window can mark
    # itself as having unsaved changes.
    changed = Signal()
    crop_mode_changed = Signal()  # crop mode switched on or off

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
        # When the window is resized, keep the middle of the view in place
        # (Qt's default keeps the top-left corner, so dragging the left edge
        # behaved differently from dragging the right edge).
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        # Redraw the whole window on every change, so the dot grid never glitches.
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # Allow files and images to be dropped onto the canvas.
        self.setAcceptDrops(True)

        # Report mouse movement even with no button held, so the cursor can
        # change when hovering over a scale/rotate handle.
        self.viewport().setMouseTracking(True)

        self._pan_last_pos = None  # set while the middle mouse button is held
        self._handle_drag = None  # set while dragging a scale/rotate/crop handle
        self.crop_item = None  # the image in crop mode, if any
        self._crop_before = None  # snapshot from when crop mode started, for undo/cancel

        # Undo history. A deque with maxlen forgets the oldest entry by itself
        # once it's full, so we never keep more than UNDO_LIMIT steps.
        self._undo = deque(maxlen=UNDO_LIMIT)
        self._redo = deque(maxlen=UNDO_LIMIT)
        self._before_left_drag = None  # snapshot taken when the left button goes down
        self._last_wheel_edit = 0.0  # when Ctrl/Alt+scroll last changed an image
        self.centerOn(0, 0)

    def zoom_level(self):
        """1.0 means 100%. m11 is the horizontal scale factor of the view."""
        return self.transform().m11()

    def view_center(self):
        """The canvas point currently in the middle of the window."""
        return self.mapToScene(self.viewport().rect().center())

    def set_view(self, zoom, center):
        """Jump to a zoom level and centre point (used when opening a board)."""
        self.resetTransform()
        self.scale(zoom, zoom)
        self.centerOn(center)

    # ---- Adding images -----------------------------------------------------

    def add_image(self, image, center, data=None, extension="png"):
        """Put a QImage on the canvas, centred on `center` (in canvas units)."""
        item = ImageItem(image, data, extension)
        item.setPos(center - QPointF(image.width() / 2, image.height() / 2))
        self.scene().addItem(item)
        return item

    def render_preview(self):
        """A small picture of the whole board, for the start panel's tiles."""
        image = QImage(PREVIEW_WIDTH, PREVIEW_HEIGHT, QImage.Format_RGB32)
        image.fill(BACKGROUND_COLOR)
        if not self.images():
            return image

        # The area that holds every image, plus a 5% margin around it.
        source = self.scene().itemsBoundingRect()
        margin = max(source.width(), source.height()) * 0.05
        source.adjust(-margin, -margin, margin, margin)

        # Hide the selection (blue outline and handles) while we take the picture.
        selected = self.scene().selectedItems()
        self.scene().clearSelection()
        painter = QPainter(image)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        # render() squeezes `source` into the picture, keeping its shape.
        self.scene().render(painter, QRectF(image.rect()), source)
        painter.end()
        for item in selected:
            item.setSelected(True)
        return image

    def images(self):
        """All images on the board, bottom-most first."""
        return [item for item in reversed(self.scene().items()) if isinstance(item, ImageItem)]

    def clear_board(self):
        """Remove every image and forget the undo history (used when opening a file)."""
        self.crop_item = None
        for item in self.images():
            self.scene().removeItem(item)
        self._undo.clear()
        self._redo.clear()

    def add_images_from_mime(self, mime, center):
        """Add every image found in dropped or pasted data. Returns True if any were added.

        "Mime data" is Qt's name for a package of data in several formats,
        used by both drag-and-drop and the clipboard.
        """
        images = []  # a list of (image, original file bytes, file extension)
        # Files, e.g. dragged in from Dolphin or copied in a file manager.
        if mime.hasUrls():
            for url in mime.urls():
                if url.isLocalFile():
                    path = Path(url.toLocalFile())
                    try:
                        data = path.read_bytes()
                    except OSError:  # e.g. it's a folder, or we may not read it
                        continue
                    image = QImage.fromData(data)
                    if not image.isNull():  # isNull means "not an image we can read"
                        extension = path.suffix.lstrip(".").lower() or "png"
                        images.append((image, data, extension))
        # Raw image data, e.g. "Copy image" in a browser, or a screenshot.
        if not images and mime.hasImage():
            data = mime.imageData()
            if isinstance(data, QPixmap):
                data = data.toImage()
            if isinstance(data, QImage) and not data.isNull():
                images.append((data, None, "png"))

        before = self.snapshot()
        for i, (image, data, extension) in enumerate(images):
            offset = QPointF(i * STACK_OFFSET, i * STACK_OFFSET)
            self.add_image(image, center + offset, data, extension)
        self.save_undo_step(before)
        return bool(images)

    # ---- Undo / redo -------------------------------------------------------
    #
    # Before any change we take a "snapshot": a list of every image with its
    # crop, position, scale and rotation. Undo puts the previous snapshot back.

    def snapshot(self):
        return [
            (item, QRect(item.crop), item.pos(), item.scale(), item.rotation())
            for item in self.scene().items()
            if isinstance(item, ImageItem)
        ]

    def restore(self, snapshot):
        wanted = [entry[0] for entry in snapshot]
        # Remove images that weren't there yet...
        for item in self.scene().items():
            if isinstance(item, ImageItem) and item not in wanted:
                self.scene().removeItem(item)
        # ...bring back ones that were deleted, and reset everyone's position.
        for item, crop, pos, scale, rotation in snapshot:
            if item.scene() is None:
                self.scene().addItem(item)
            item.set_crop(crop)  # before setPos: set_crop nudges the position itself
            item.setPos(pos)
            item.setScale(scale)
            item.setRotation(rotation)

    def save_undo_step(self, before):
        """Call right AFTER a change, with the snapshot from just BEFORE it."""
        if before is None or before == self.snapshot():
            return  # nothing actually changed, e.g. a click that only selected
        self._undo.append(before)
        self._redo.clear()  # a new change makes the old "future" invalid
        self.changed.emit()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        self.finish_crop()
        if self._undo:
            self._redo.append(self.snapshot())
            self.restore(self._undo.pop())
            self.changed.emit()

    def redo(self):
        self.finish_crop()
        if self._redo:
            self._undo.append(self.snapshot())
            self.restore(self._redo.pop())
            self.changed.emit()

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

    # ---- Crop mode ---------------------------------------------------------

    def toggle_crop(self):
        """Start cropping the selected image, or finish if already cropping."""
        if self.crop_item is not None:
            self.finish_crop()
            return
        selected = self.scene().selectedItems()
        if not selected:
            return
        self.crop_item = selected[0]
        self._crop_before = self.snapshot()
        self.crop_item.set_cropping(True)
        self.crop_mode_changed.emit()

    def finish_crop(self):
        """Leave crop mode, keeping the crop. The whole session is one undo step."""
        if self.crop_item is None:
            return
        self.crop_item.set_cropping(False)
        self.crop_item = None
        self.crop_mode_changed.emit()
        self.save_undo_step(self._crop_before)

    def cancel_crop(self):
        """Leave crop mode and put everything back how it was."""
        if self.crop_item is None:
            return
        self.crop_item.set_cropping(False)
        self.crop_item = None
        self.crop_mode_changed.emit()
        self.restore(self._crop_before)

    # ---- Other actions (used by keys and the tool panel) -------------------

    def delete_selected(self):
        self.finish_crop()
        before = self.snapshot()
        for item in self.scene().selectedItems():
            self.scene().removeItem(item)
        self.save_undo_step(before)

    def fit_all(self):
        """Zoom and pan so every image fits in the window."""
        if not self.images():
            return
        area = self.scene().itemsBoundingRect()
        margin = max(area.width(), area.height()) * FIT_MARGIN
        area.adjust(-margin, -margin, margin, margin)
        # fitInView is a ready-made Qt tool: it zooms and centres on `area`.
        self.fitInView(area, Qt.KeepAspectRatio)
        # Keep within our usual zoom limits.
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom_level()))
        self.set_view(zoom, area.center())

    def event(self, event):
        # Esc is also a window-wide shortcut (it closes the start panel). Qt
        # asks the focused widget first with a "ShortcutOverride" event;
        # while cropping, we say "this key is mine" so Esc cancels the crop.
        if (
            event.type() == QEvent.ShortcutOverride
            and self.crop_item is not None
            and event.key() == Qt.Key_Escape
        ):
            event.accept()
            return True
        return super().event(event)

    # ---- Keyboard ----------------------------------------------------------

    def keyPressEvent(self, event):
        if self.crop_item is not None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_crop()
                return
            if event.key() == Qt.Key_Escape:
                self.cancel_crop()
                return
        if event.key() == Qt.Key_C and event.modifiers() == Qt.NoModifier:
            self.toggle_crop()
            return
        if event.key() == Qt.Key_F and event.modifiers() == Qt.NoModifier:
            self.fit_all()
            return
        # Pasting while cropping finishes the crop first.
        if self.crop_item is not None and event.matches(QKeySequence.Paste):
            self.finish_crop()

        if event.matches(QKeySequence.Paste):
            # Paste where the mouse is, or in the middle if it's outside the window.
            mouse = self.viewport().mapFromGlobal(QCursor.pos())
            if not self.viewport().rect().contains(mouse):
                mouse = self.viewport().rect().center()
            self.add_images_from_mime(QApplication.clipboard().mimeData(), self.mapToScene(mouse))
            return

        if event.matches(QKeySequence.Undo):  # Ctrl+Z
            self.undo()
            return
        if event.matches(QKeySequence.Redo):  # Ctrl+Shift+Z
            self.redo()
            return

        if event.key() == Qt.Key_Delete:
            self.delete_selected()
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

        if selected and (ctrl or alt):
            before = self.snapshot()
            for item in selected:
                if ctrl:
                    item.setScale(max(MIN_IMAGE_SCALE, item.scale() * IMAGE_SCALE_STEP**notches))
                else:
                    item.setRotation((item.rotation() + ROTATE_STEP * notches) % 360)
            # A quick burst of scroll notches counts as one undo step, not one per notch.
            now = time.monotonic()
            if now - self._last_wheel_edit > WHEEL_UNDO_PAUSE:
                self.save_undo_step(before)
            self._last_wheel_edit = now
            return

        target = self.zoom_level() * ZOOM_STEP**notches
        target = max(MIN_ZOOM, min(MAX_ZOOM, target))
        factor = target / self.zoom_level()
        self.scale(factor, factor)

    # ---- Handles: find which one (if any) is under the mouse ---------------

    def handle_at(self, pos, ctrl=False):
        """Is `pos` (window pixels) on a handle of a selected image?

        Returns (item, mode, edges) or None. `mode` is one of:
          "crop"   - on an edge or corner, in crop mode or with Ctrl held;
                     `edges` says which edges move, e.g. {"left", "top"}
          "scale"  - on a corner
          "rotate" - just outside a corner
        """
        scene_pos = self.mapToScene(pos)
        point = QPointF(pos)
        candidates = self.scene().selectedItems()
        if self.crop_item is not None and self.crop_item not in candidates:
            candidates.insert(0, self.crop_item)

        for item in candidates:
            corners = [QPointF(self.mapFromScene(item.mapToScene(c))) for c in item.corners()]

            if item is self.crop_item or ctrl:
                edges = self.crop_edges_at(point, corners)
                if edges is not None:
                    return item, "crop", edges
                if item is self.crop_item:
                    continue  # no scaling or rotating while in crop mode

            for corner in corners:
                distance = math.dist((point.x(), point.y()), (corner.x(), corner.y()))
                if distance <= HANDLE_GRAB:
                    return item, "scale", None
                outside = not item.contains(item.mapFromScene(scene_pos))
                if distance <= ROTATE_GRAB and outside:
                    return item, "rotate", None
        return None

    def crop_edges_at(self, point, corners):
        """Which crop edges `point` (screen pixels) grabs, given the image's
        corners on screen. Corners grab two edges, sides one. None = no edge."""
        for corner, edges in zip(corners, CORNER_EDGES):
            if math.dist((point.x(), point.y()), (corner.x(), corner.y())) <= HANDLE_GRAB:
                return edges
        for name, a, b in SIDES:
            if distance_to_segment(point, corners[a], corners[b]) <= HANDLE_GRAB:
                return {name}
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

        if event.button() == Qt.RightButton:
            # Nothing uses the right button (yet). Don't pass it on: Qt's
            # scene treats any click nobody wants as "clicked on empty
            # space" and clears the selection, even mid-drag.
            return

        if event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier:
            # Alt+drag moves the whole window. startSystemMove hands the drag
            # to the window manager (KWin), so it feels native: snapping to
            # screen edges and all. Works on Wayland too.
            self.window().windowHandle().startSystemMove()
            return

        if event.button() == Qt.LeftButton:
            ctrl = bool(event.modifiers() & Qt.ControlModifier)
            hit = self.handle_at(pos, ctrl)
            # Clicking away from the image being cropped finishes cropping.
            if self.crop_item is not None and hit is None and self.itemAt(pos) is not self.crop_item:
                self.finish_crop()
            # Whatever this left-drag does (move, scale, rotate, crop), it
            # becomes one undo step when the button is released.
            self._before_left_drag = self.snapshot()
            if hit is not None:
                item, mode, edges = hit
                scene_pos = self.mapToScene(pos)
                # Remember how things were at the start of the drag; every
                # mouse move then compares against this starting point.
                self._handle_drag = {
                    "item": item,
                    "mode": mode,
                    "edges": edges,
                    "start_crop": QRectF(item.crop),
                    "start_scale": item.scale(),
                    "start_distance": max(1e-6, self.distance_from_center(item, scene_pos)),
                    "start_rotation": item.rotation(),
                    "start_angle": self.angle_from_center(item, scene_pos),
                }
                # Ctrl+drag crop: show the ghost of the cut-off parts while
                # dragging, just like crop mode does.
                if mode == "crop":
                    item.set_cropping(True)
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
            if drag["mode"] == "crop":
                self.drag_crop_edges(item, drag["edges"], drag["start_crop"], scene_pos)
            elif drag["mode"] == "scale":
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
            hit = self.handle_at(pos, bool(event.modifiers() & Qt.ControlModifier))
            if hit is None:
                self.viewport().unsetCursor()
            elif hit[1] == "crop":
                self.viewport().setCursor(self.crop_cursor(hit[2]))
            elif hit[1] == "scale":
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.CrossCursor)

        super().mouseMoveEvent(event)

    def drag_crop_edges(self, item, edges, start, scene_pos):
        """Move the grabbed crop edges to the mouse.

        mapFromScene turns the mouse position into the image's own pixel
        coordinates, so this works the same for scaled and rotated images.
        """
        mouse = item.mapFromScene(scene_pos)
        full = QRectF(item.full_pixmap.rect())
        r = QRectF(start)
        # Each edge follows the mouse, but stays inside the full picture and
        # at least MIN_CROP_SIZE away from the opposite edge.
        if "left" in edges:
            r.setLeft(max(full.left(), min(mouse.x(), r.right() - MIN_CROP_SIZE)))
        if "right" in edges:
            r.setRight(min(full.right(), max(mouse.x(), r.left() + MIN_CROP_SIZE)))
        if "top" in edges:
            r.setTop(max(full.top(), min(mouse.y(), r.bottom() - MIN_CROP_SIZE)))
        if "bottom" in edges:
            r.setBottom(min(full.bottom(), max(mouse.y(), r.top() + MIN_CROP_SIZE)))
        item.set_crop(r.toRect())  # toRect rounds to whole pixels

    def crop_cursor(self, edges):
        if edges in ({"left"}, {"right"}):
            return Qt.SizeHorCursor
        if edges in ({"top"}, {"bottom"}):
            return Qt.SizeVerCursor
        if edges in ({"left", "top"}, {"right", "bottom"}):
            return Qt.SizeFDiagCursor
        return Qt.SizeBDiagCursor

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton and self._pan_last_pos is not None:
            self._pan_last_pos = None
            self.viewport().unsetCursor()
            return
        if event.button() == Qt.LeftButton:
            if self._handle_drag is not None:
                item = self._handle_drag["item"]
                if self._handle_drag["mode"] == "crop" and item is not self.crop_item:
                    item.set_cropping(False)  # quick crop done: hide the ghost again
                self._handle_drag = None
            else:
                super().mouseReleaseEvent(event)  # let Qt finish moving the images
            # In crop mode the whole session becomes one undo step when it
            # ends, so single drags aren't saved separately.
            if self.crop_item is None:
                self.save_undo_step(self._before_left_drag)
            self._before_left_drag = None
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Double-click an image to straighten it (rotation back to 0, "north up").
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and isinstance(item, ImageItem):
            before = self.snapshot()
            item.setRotation(0)
            self.save_undo_step(before)
            return
        super().mouseDoubleClickEvent(event)

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


        