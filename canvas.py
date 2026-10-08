"""The canvas: an endless dark surface you can pan around and zoom into."""

import functools
import math
import time
from collections import deque

from pathlib import Path

from PySide6.QtCore import QEvent, QLineF, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QGraphicsScene, QGraphicsView

from board_item import HANDLE_GRAB, ROTATE_GRAB, BoardItem
from context_menu import show_context_menu
from image_item import MIN_CROP_SIZE, ImageItem
from note_item import NoteItem
from platform_support import is_delete_key, start_window_move

# Look and feel. Tweak these freely.
# Colors borrowed from Apple's dark-mode system grays.
BACKGROUND_COLOR = QColor("#1C1C1E")  # Apple "systemGray6"
DOT_COLOR = QColor("#3A3A3C")  # Apple "systemGray4"
SELECTION_BOX_FILL = QColor(255, 255, 255, 20)  # light gray, very see-through (alpha 0-255)
SELECTION_BOX_BORDER = QColor(255, 255, 255, 60)
SNAP_GUIDE_COLOR = QColor("#FF375F")  # Apple "systemPink": stands out from the blue selection
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
DUPLICATE_OFFSET = 20  # Ctrl+D puts the copy this many screen pixels down and right
ARRANGE_GAP = 10  # space between arranged images, in screen pixels
SNAP_DISTANCE = 8  # dragged images snap when an edge is this close, in screen pixels

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

        self._pan_last_pos = None  # set while panning (middle button, or Space + left)
        self._pan_button = None  # the mouse button that is panning
        self._space_held = False  # Space down: left-drag pans (for trackpads)
        self._window_drag = None  # set while moving the window ourselves (see Alt+drag)
        self._handle_drag = None  # set while dragging a scale/rotate/crop handle
        self._box = None  # set while dragging a selection box on empty canvas
        self.crop_item = None  # the image in crop mode, if any
        self._crop_before = None  # snapshot from when crop mode started, for undo/cancel
        self.editing_note = None  # the note you're typing in, if any
        self._edit_before = None  # snapshot from when typing started, for undo
        self._moving = False  # True while Qt drags images around (left-drag on an image)
        self._guides = []  # snap guide lines to draw, in canvas units

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
        """Put a QImage (or QPixmap) on the canvas, centred on `center` (in canvas units)."""
        item = ImageItem(image, data, extension)
        item.setPos(center - QPointF(image.width() / 2, image.height() / 2))
        self.place_item(item)
        return item

    def add_note(self, text, top_left, scale=None):
        """Put a text note on the canvas with its top-left corner at `top_left`.

        Without a `scale`, the note is sized to look the same at any zoom level.
        """
        note = NoteItem(text)
        note.setPos(top_left)
        note.setScale(scale if scale is not None else 1 / self.zoom_level())
        self.place_item(note)
        return note

    def place_item(self, item):
        """Put a new image or note on the board, on top of everything else."""
        existing = self.board_items()
        item.setZValue(existing[-1].zValue() + 1 if existing else 0)
        self.scene().addItem(item)
        if isinstance(item, NoteItem):
            # "Queued" means: call finish_editing a moment later, once Qt is
            # done handling the focus change, not in the middle of it.
            item.editing_finished.connect(self.finish_editing, Qt.QueuedConnection)

    def render_preview(self):
        """A small picture of the whole board, for the start panel's tiles."""
        image = QImage(PREVIEW_WIDTH, PREVIEW_HEIGHT, QImage.Format_RGB32)
        image.fill(BACKGROUND_COLOR)
        if not self.board_items():
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

    def board_items(self):
        """Everything on the board (images and notes), bottom-most first."""
        return [item for item in reversed(self.scene().items()) if isinstance(item, BoardItem)]

    def images(self):
        """All images on the board, bottom-most first."""
        return [item for item in self.board_items() if isinstance(item, ImageItem)]

    def selected_items(self):
        """The selected images and notes, bottom-most first."""
        return [item for item in self.board_items() if item.isSelected()]

    def selected_images(self):
        return [item for item in self.selected_items() if isinstance(item, ImageItem)]

    def clear_board(self):
        """Remove everything and forget the undo history (used when opening a file)."""
        self.finish_editing()
        self.crop_item = None
        for item in self.board_items():
            self.scene().removeItem(item)
        self._undo.clear()
        self._redo.clear()

    def mouse_scene_pos(self):
        """Where the mouse is on the canvas, or the middle of the window if it's outside."""
        mouse = self.viewport().mapFromGlobal(QCursor.pos())
        if not self.viewport().rect().contains(mouse):
            mouse = self.viewport().rect().center()
        return self.mapToScene(mouse)

    def add_from_mime(self, mime, center):
        """Add every image found in dropped or pasted data. Returns True if anything was added.

        Plain text (with no files or images) becomes a text note instead.

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

        text = mime.text().strip() if mime.hasText() and not mime.hasUrls() else ""

        self.settle()
        before = self.snapshot()
        for i, (image, data, extension) in enumerate(images):
            offset = QPointF(i * STACK_OFFSET, i * STACK_OFFSET)
            self.add_image(image, center + offset, data, extension)
        if not images and text:
            self.add_note(text, center)
        self.save_undo_step(before)
        return bool(images or text)

    # ---- Undo / redo -------------------------------------------------------
    #
    # Before any change we take a "snapshot": a list of every image and note
    # with its "state" (position, scale, rotation, stacking height, crop,
    # text, ...; see state() in image_item.py and note_item.py). Undo puts
    # the previous snapshot back.

    def snapshot(self):
        return [(item, item.state()) for item in self.board_items()]

    def restore(self, snapshot):
        wanted = [item for item, _state in snapshot]
        # Remove things that weren't there yet...
        for item in self.board_items():
            if item not in wanted:
                self.scene().removeItem(item)
        # ...bring back ones that were deleted, and put everyone back how they were.
        for item, state in snapshot:
            if item.scene() is None:
                self.scene().addItem(item)
            item.set_state(state)

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
        self.settle()
        if self._undo:
            self._redo.append(self.snapshot())
            self.restore(self._undo.pop())
            self.changed.emit()

    def redo(self):
        self.settle()
        if self._redo:
            self._undo.append(self.snapshot())
            self.restore(self._redo.pop())
            self.changed.emit()

    # ---- Drag and drop -----------------------------------------------------

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasImage() or mime.hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        # Must be overridden too, or Qt passes it to the scene, which refuses it.
        event.acceptProposedAction()

    def dropEvent(self, event):
        center = self.mapToScene(event.position().toPoint())
        if self.add_from_mime(event.mimeData(), center):
            event.acceptProposedAction()

    # ---- Crop mode ---------------------------------------------------------

    def toggle_crop(self):
        """Start cropping the selected image, or finish if already cropping."""
        if self.crop_item is not None:
            self.finish_crop()
            return
        self.finish_editing()
        selected = self.selected_images()
        if not selected:
            return
        self.crop_item = selected[-1]  # the top-most one
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

    def settle(self):
        """Finish whatever we're in the middle of (cropping, typing a note)
        before doing something else."""
        self.finish_editing()
        self.finish_crop()

    # ---- Text notes --------------------------------------------------------

    def new_note_at(self, scene_pos):
        """Make an empty note at `scene_pos`, and start typing in it."""
        self.settle()
        before = self.snapshot()
        self.start_editing(self.add_note("", scene_pos), before)

    def new_note_at_mouse(self):
        self.new_note_at(self.mouse_scene_pos())

    def start_editing(self, note, before):
        """Start typing in `note`. `before` is the snapshot to undo back to."""
        self.settle()
        self.editing_note = note
        self._edit_before = before
        self.scene().clearSelection()  # no handles while typing
        note.start_editing()

    def finish_editing(self):
        """Stop typing. An empty note is thrown away. Typing is one undo step."""
        note = self.editing_note
        if note is None:
            return
        self.editing_note = None
        note.stop_editing()
        if not note.toPlainText().strip():
            self.scene().removeItem(note)
        self.save_undo_step(self._edit_before)

    # ---- Other actions (used by keys, the tool panel and the menu) ---------

    def delete_selected(self):
        self.settle()
        before = self.snapshot()
        for item in self.scene().selectedItems():
            self.scene().removeItem(item)
        self.save_undo_step(before)

    def select_all(self):
        self.settle()
        for item in self.board_items():
            item.setSelected(True)

    def copy_selected(self):
        """Copy the top-most selected image to the clipboard, as you see it
        (cropped, flipped, gray). With only notes selected, copy their text."""
        selected = self.selected_items()
        images = [item for item in selected if isinstance(item, ImageItem)]
        if images:
            # pixmap() is exactly the visible part, at the image's full resolution.
            QApplication.clipboard().setImage(images[-1].pixmap().toImage())
        elif selected:
            # Top to bottom, like reading the board.
            notes = sorted(selected, key=lambda note: note.scene_rect().top())
            QApplication.clipboard().setText("\n\n".join(note.toPlainText() for note in notes))

    def duplicate_selected(self):
        """Copies of the selected things, a bit down and to the right, on top of everything."""
        self.settle()
        originals = self.selected_items()  # bottom-most first, so the copies stack the same way
        if not originals:
            return
        before = self.snapshot()
        shift = DUPLICATE_OFFSET / self.zoom_level()
        self.scene().clearSelection()
        for item in originals:
            copy = item.clone()
            copy.moveBy(shift, shift)
            self.place_item(copy)
            copy.setSelected(True)  # so you can drag the copies straight away
        self.save_undo_step(before)

    def toggle_grayscale(self):
        """Black and white on or off for the selected images. If some are in
        color and some aren't, they all become black and white."""
        self.settle()
        images = self.selected_images()
        if not images:
            return
        before = self.snapshot()
        gray = not self.selected_all_gray()
        for item in images:
            item.set_grayscale(gray)
        self.save_undo_step(before)

    def selected_all_gray(self):
        images = self.selected_images()
        return bool(images) and all(item.grayscale for item in images)

    def flip_selected(self, horizontal):
        self.settle()
        before = self.snapshot()
        for item in self.selected_images():
            item.flip(horizontal)
        self.save_undo_step(before)

    def flip_horizontal(self):
        self.flip_selected(True)

    def flip_vertical(self):
        self.flip_selected(False)

    def arrange_selected(self):
        """Lay the selected things out in neat rows, starting where they are now.

        Rows are filled left to right, and each row is as wide as makes the
        whole block roughly the shape of the window.
        """
        self.settle()
        items = self.selected_items()
        if len(items) < 2:
            return
        before = self.snapshot()
        rects = {item: item.scene_rect() for item in items}

        # Keep the order you see: group into rows (top to bottom), then
        # read each row left to right.
        items.sort(key=lambda item: rects[item].center().y())
        rows = []
        row_bottom = None
        for item in items:
            if rows and rects[item].center().y() < row_bottom:
                rows[-1].append(item)
                row_bottom = max(row_bottom, rects[item].bottom())
            else:
                rows.append([item])
                row_bottom = rects[item].bottom()
        order = [item for row in rows for item in sorted(row, key=lambda i: rects[i].left())]

        gap = ARRANGE_GAP / self.zoom_level()
        area = sum((r.width() + gap) * (r.height() + gap) for r in rects.values())
        window = self.viewport().rect()
        width = max(max(r.width() for r in rects.values()), math.sqrt(area * window.width() / window.height()))

        start = functools.reduce(QRectF.united, rects.values())  # around all of them
        x, y, row_height = start.left(), start.top(), 0
        for item in order:
            r = rects[item]
            if x > start.left() and x + r.width() > start.left() + width:
                x, y, row_height = start.left(), y + row_height + gap, 0  # next row
            item.setPos(item.pos() + QPointF(x, y) - r.topLeft())
            x += r.width() + gap
            row_height = max(row_height, r.height())
        self.save_undo_step(before)

    # ---- Stacking order: which image is drawn on top ----------------------
    #
    # Every item has a "Z value": higher Z is drawn on top. We keep the
    # images numbered 0, 1, 2, ... from the bottom up, and reordering just
    # shuffles the list and hands out the numbers again.

    def restack(self, order):
        """Give the items in `order` (bottom-most first) Z values 0, 1, 2, ..."""
        self.settle()
        before = self.snapshot()
        for z, item in enumerate(order):
            item.setZValue(z)
        self.save_undo_step(before)

    def bring_to_front(self):
        order = self.board_items()
        self.restack([i for i in order if not i.isSelected()] + [i for i in order if i.isSelected()])

    def send_to_back(self):
        order = self.board_items()
        self.restack([i for i in order if i.isSelected()] + [i for i in order if not i.isSelected()])

    def raise_selected(self):
        """Move each selected image up past the next image that overlaps it.

        Images that don't overlap don't count: swapping with an image on the
        other side of the board would look like nothing happened.
        """
        order = self.board_items()
        # Top-most first, so the selected images don't leapfrog each other.
        for item in sorted(self.scene().selectedItems(), key=lambda i: -i.zValue()):
            here = order.index(item)
            for above in range(here + 1, len(order)):
                other = order[above]
                if not other.isSelected() and item.collidesWithItem(other):
                    order.insert(above, order.pop(here))  # now sits just above `other`
                    break
        self.restack(order)

    def lower_selected(self):
        """Like raise_selected, but downwards."""
        order = self.board_items()
        for item in sorted(self.scene().selectedItems(), key=lambda i: i.zValue()):
            here = order.index(item)
            for below in range(here - 1, -1, -1):
                other = order[below]
                if not other.isSelected() and item.collidesWithItem(other):
                    order.insert(below, order.pop(here))  # now sits just below `other`
                    break
        self.restack(order)

    def straighten_selected(self):
        """Turn the selected images back to 0 degrees ("north up")."""
        self.settle()
        before = self.snapshot()
        for item in self.scene().selectedItems():
            item.setRotation(0)
        self.save_undo_step(before)

    def any_selected_rotated(self):
        return any(item.rotation() != 0 for item in self.scene().selectedItems())

    def fit_all(self):
        """Zoom and pan so everything fits in the window."""
        if not self.board_items():
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
        # while cropping or typing, we say "this key is mine" so Esc ends that.
        if (
            event.type() == QEvent.ShortcutOverride
            and (self.crop_item is not None or self.editing_note is not None)
            and event.key() == Qt.Key_Escape
        ):
            event.accept()
            return True
        return super().event(event)

    # ---- Keyboard ----------------------------------------------------------

    def keyPressEvent(self, event):
        # While typing in a note, every key goes to the note. Esc stops typing.
        if self.editing_note is not None:
            if event.key() == Qt.Key_Escape:
                self.finish_editing()
                return
            super().keyPressEvent(event)  # QGraphicsView passes it on to the note
            return

        # Holding a key makes the system repeat it; only the first press counts.
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_held = True
            self.update_pan_cursor()
            return

        if self.crop_item is not None:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_crop()
                return
            if event.key() == Qt.Key_Escape:
                self.cancel_crop()
                return

        if event.matches(QKeySequence.Paste):  # Ctrl+V
            self.add_from_mime(QApplication.clipboard().mimeData(), self.mouse_scene_pos())
            return
        if event.matches(QKeySequence.Undo):  # Ctrl+Z
            self.undo()
            return
        if event.matches(QKeySequence.Redo):  # Ctrl+Shift+Z
            self.redo()
            return

        if is_delete_key(event.key()):
            self.delete_selected()
            return

        # (key, modifier keys held) -> what to do.
        actions = {
            (Qt.Key_C, Qt.NoModifier): self.toggle_crop,
            (Qt.Key_F, Qt.NoModifier): self.fit_all,
            (Qt.Key_G, Qt.NoModifier): self.toggle_grayscale,
            (Qt.Key_H, Qt.NoModifier): self.flip_horizontal,
            (Qt.Key_V, Qt.NoModifier): self.flip_vertical,
            (Qt.Key_A, Qt.NoModifier): self.arrange_selected,
            (Qt.Key_T, Qt.NoModifier): self.new_note_at_mouse,
            (Qt.Key_A, Qt.ControlModifier): self.select_all,
            (Qt.Key_C, Qt.ControlModifier): self.copy_selected,
            (Qt.Key_D, Qt.ControlModifier): self.duplicate_selected,
            # Stacking order: Ctrl+] / Ctrl+[ = all the way, ] / [ = one step.
            (Qt.Key_BracketRight, Qt.ControlModifier): self.bring_to_front,
            (Qt.Key_BracketLeft, Qt.ControlModifier): self.send_to_back,
            (Qt.Key_BracketRight, Qt.NoModifier): self.raise_selected,
            (Qt.Key_BracketLeft, Qt.NoModifier): self.lower_selected,
        }
        action = actions.get((event.key(), event.modifiers()))
        if action is not None:
            action()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat() and self._space_held:
            self.release_space()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event):
        # If Space is let go while another window has focus, we never hear
        # about it, so forget it now rather than stay stuck in pan mode.
        if self._space_held:
            self.release_space()
        super().focusOutEvent(event)

    def release_space(self):
        self._space_held = False
        self.update_pan_cursor()

    def update_pan_cursor(self):
        """Closed hand while panning, open hand while Space is held, else normal."""
        if self._pan_last_pos is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self._space_held:
            self.viewport().setCursor(Qt.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

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
        """Is `pos` (window pixels) on a handle of a selected image or note?

        Returns (item, mode, edges) or None. `mode` is one of:
          "crop"   - on an image's edge or corner, in crop mode or with Ctrl held;
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

            if item is self.crop_item or (ctrl and isinstance(item, ImageItem)):
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

        # Middle-drag pans. So does left-drag while Space is held, for
        # trackpads and Mac mice that have no middle button.
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_held):
            self._pan_last_pos = pos
            self._pan_button = event.button()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return

        if event.button() == Qt.RightButton:
            # The menu itself opens in contextMenuEvent. Don't pass the click
            # on: Qt's scene treats any click nobody wants as "clicked on
            # empty space" and clears the selection, even mid-drag.
            return

        if event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier:
            # Alt+drag (Option+drag on a Mac) moves the whole window. Normally
            # the operating system takes over the drag, so it feels native.
            # If it can't, we move the window ourselves in mouseMoveEvent:
            # remember where in the window you grabbed it.
            if not start_window_move(self.window()):
                grabbed = event.globalPosition().toPoint()
                self._window_drag = grabbed - self.window().frameGeometry().topLeft()
            return

        if event.button() == Qt.LeftButton:
            # Clicking outside the note you're typing in stops typing.
            if self.editing_note is not None and self.itemAt(pos) is not self.editing_note:
                self.finish_editing()
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

            under_mouse = self.itemAt(pos)
            if not isinstance(under_mouse, BoardItem):
                # Empty canvas: start a selection box. Ctrl adds to the
                # current selection instead of starting over.
                if not ctrl:
                    self.scene().clearSelection()
                self._box = {"start": pos, "end": pos, "kept": set(self.scene().selectedItems())}
                return
            # On an image or note: Qt will drag the selection around, and we
            # snap it to the other things on the board. (Not on the note
            # you're typing in: there, dragging selects text.)
            self._moving = under_mouse is not self.editing_note

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self._window_drag is not None:
            self.window().move(event.globalPosition().toPoint() - self._window_drag)
            return

        if self._pan_last_pos is not None:
            delta: QPoint = pos - self._pan_last_pos
            self._pan_last_pos = pos
            # Panning = moving the hidden scrollbars the opposite way.
            h = self.horizontalScrollBar()
            v = self.verticalScrollBar()
            h.setValue(h.value() - delta.x())
            v.setValue(v.value() - delta.y())
            return

        if self._box is not None:
            self._box["end"] = pos
            # Select every image the box touches, plus the ones kept from before.
            box_on_canvas = self.mapToScene(self.box_rect())
            touched = set(self.scene().items(box_on_canvas, Qt.IntersectsItemShape))
            for item in self.board_items():
                item.setSelected(item in touched or item in self._box["kept"])
            self.viewport().update()
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
        # (Not while Space is held: then the cursor stays a hand.)
        if event.buttons() == Qt.NoButton and not self._space_held:
            hit = self.handle_at(pos, bool(event.modifiers() & Qt.ControlModifier))
            if hit is None:
                self.viewport().unsetCursor()
            elif hit[1] == "crop":
                self.viewport().setCursor(self.crop_cursor(hit[2]))
            elif hit[1] == "scale":
                self.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.viewport().setCursor(Qt.CrossCursor)

        super().mouseMoveEvent(event)  # Qt moves the dragged images here

        if self._moving and event.buttons() & Qt.LeftButton:
            # Hold Shift to move freely, without snapping.
            self.snap_selection(free=bool(event.modifiers() & Qt.ShiftModifier))

    # ---- Snapping: line up with other images while dragging -----------------

    def snap_selection(self, free):
        """Nudge the dragged images so their edges or middle line up with a
        nearby image's edges or middle, and remember guide lines to draw.

        Qt places dragged images from where the drag started plus how far
        the mouse moved, so our nudge doesn't add up from move to move.
        """
        self._guides = []
        moving = self.selected_items()
        others = [item.scene_rect() for item in self.board_items() if not item.isSelected()]
        if moving and others and not free:
            box = functools.reduce(QRectF.united, (item.scene_rect() for item in moving))
            reach = SNAP_DISTANCE / self.zoom_level()  # screen pixels -> canvas units

            def lines_x(r):
                return (r.left(), r.center().x(), r.right())

            def lines_y(r):
                return (r.top(), r.center().y(), r.bottom())

            dx = self.closest_snap(lines_x(box), [x for r in others for x in lines_x(r)], reach)
            dy = self.closest_snap(lines_y(box), [y for r in others for y in lines_y(r)], reach)
            for item in moving:
                item.moveBy(dx or 0, dy or 0)
            box.translate(dx or 0, dy or 0)

            # A guide line for every edge or middle that now lines up (to
            # within half a screen pixel), long enough to reach from the
            # dragged images to the other image.
            tolerance = 0.5 / self.zoom_level()
            for r in others:
                if dx is not None:
                    for x in lines_x(r):
                        if any(abs(x - mine) < tolerance for mine in lines_x(box)):
                            top, bottom = min(r.top(), box.top()), max(r.bottom(), box.bottom())
                            self._guides.append(QLineF(x, top, x, bottom))
                if dy is not None:
                    for y in lines_y(r):
                        if any(abs(y - mine) < tolerance for mine in lines_y(box)):
                            left, right = min(r.left(), box.left()), max(r.right(), box.right())
                            self._guides.append(QLineF(left, y, right, y))
        self.viewport().update()

    @staticmethod
    def closest_snap(mine, theirs, reach):
        """The smallest shift (within `reach`) that puts one of `mine` exactly
        on one of `theirs`, or None if nothing is close enough."""
        best = None
        for a in mine:
            for b in theirs:
                shift = b - a
                if abs(shift) <= reach and (best is None or abs(shift) < abs(best)):
                    best = shift
        return best

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
        if self._pan_last_pos is not None and event.button() == self._pan_button:
            self._pan_last_pos = None
            self._pan_button = None
            self.update_pan_cursor()
            return
        if event.button() == Qt.LeftButton and self._window_drag is not None:
            self._window_drag = None
            return
        if event.button() == Qt.LeftButton and self._box is not None:
            self._box = None
            self.viewport().update()  # make the box disappear
            return
        if event.button() == Qt.LeftButton:
            self._moving = False
            self._guides = []  # the snap guides disappear with the next repaint
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

    def contextMenuEvent(self, event):
        """Right-click: Qt sends this separately, right after the mouse press."""
        if QApplication.mouseButtons() & Qt.LeftButton:
            return  # in the middle of a left-drag: don't interrupt it
        # Right-clicking an image that isn't selected selects just that one,
        # like in a file manager. On a selected image, the selection stays.
        item = self.itemAt(event.pos())
        if isinstance(item, BoardItem) and item is not self.editing_note and not item.isSelected():
            self.scene().clearSelection()
            item.setSelected(True)
        show_context_menu(self, event.globalPos(), self.mapToScene(event.pos()))

    def mouseDoubleClickEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        # Double-click a note to type in it. (In the note you're already
        # typing in, Qt's double-click selects a word instead.)
        if event.button() == Qt.LeftButton and isinstance(item, NoteItem) and item is not self.editing_note:
            self.start_editing(item, self.snapshot())
            return
        # Double-click an image to bring it to the front.
        if event.button() == Qt.LeftButton and isinstance(item, ImageItem):
            order = self.board_items()
            order.remove(item)
            self.restack(order + [item])
            return
        super().mouseDoubleClickEvent(event)

    # ---- Selection box -----------------------------------------------------

    def box_rect(self):
        """The selection box in window pixels. normalized() makes dragging up or left work too."""
        return QRect(self._box["start"], self._box["end"]).normalized()

    def drawForeground(self, painter, rect):
        """Painted on top of the images: snap guides and the selection box, while dragging."""
        if self._guides:
            pen = QPen(SNAP_GUIDE_COLOR, 1)
            pen.setCosmetic(True)  # 1 screen pixel wide at any zoom
            painter.setPen(pen)
            painter.drawLines(self._guides)
        if self._box is None:
            return
        painter.save()
        painter.resetTransform()  # draw in window pixels, not canvas units
        painter.setPen(QPen(SELECTION_BOX_BORDER, 1))
        painter.setBrush(SELECTION_BOX_FILL)
        painter.drawRect(self.box_rect())
        painter.restore()

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


        