"""The start panel: a floating card with a sidebar (new / open) and your recent boards."""

import math

from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# Colors: Apple dark-mode "elevated" grays.
PANEL_COLOR = QColor("#2C2C2E")
BORDER_COLOR = QColor("#3A3A3C")
TILE_COLOR = QColor("#3A3A3C")
EMPTY_TILE_COLOR = QColor("#323234")  # a free slot, a bit dimmer than a real tile
TITLE_COLOR = QColor("#E5E5EA")
LABEL_COLOR = QColor("#8E8E93")
ACCENT_COLOR = QColor("#0A84FF")  # Apple "systemBlue": the main button
ACCENT_HOVER_COLOR = QColor("#409CFF")
BUTTON_HOVER_COLOR = QColor("#3A3A3C")
FOCUS_RING_COLOR = QColor("#0A84FF")

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
SIDEBAR_WIDTH = 220  # the left column with the buttons
BUTTON_HEIGHT = 36
BUTTON_GAP = 8
BUTTON_RADIUS = 10

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
    """Floats in the middle of its parent (the canvas) and stays centred.

    Things you can click or reach with the arrow keys are called "targets":
    ("button", 0) is the first sidebar button, ("tile", 2) the third tile.
    """

    # Wires for the window to connect to.
    new_board_requested = Signal()
    open_requested = Signal()
    open_path_requested = Signal(str)  # a recent board was picked; carries its path

    def __init__(self, parent):
        super().__init__(parent)

        # A soft shadow underneath, so the panel looks like it floats.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        # The sidebar buttons: (text, shortcut, signal to emit, is it the main one?)
        self.buttons = [
            ("New board", QKeySequence(QKeySequence.New), self.new_board_requested, True),
            ("Open board…", QKeySequence(QKeySequence.Open), self.open_requested, False),
        ]
        self.recent = []  # list of (path, preview QImage or None), newest first

        self.active = None  # the highlighted target (mouse hover or arrow keys), or None
        # True while using the arrow keys: then we also draw a focus ring.
        self.keyboard_navigating = False
        self.setMouseTracking(True)  # get mouse moves even without a button held
        # Accept keyboard focus, so arrow keys come to us instead of the canvas.
        self.setFocusPolicy(Qt.StrongFocus)

        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)
        # Watch the parent's events, so we notice when it's resized.
        parent.installEventFilter(self)
        self.center_in_parent()

    def set_recent(self, recent):
        """Show these boards: a list of (path, preview image or None)."""
        self.recent = recent[:4]
        self.active = None
        self.update()

    def center_in_parent(self):
        parent = self.parentWidget()
        self.move((parent.width() - self.width()) // 2, (parent.height() - self.height()) // 2)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.center_in_parent()
        return False  # False = "I only looked"; the parent still handles the event

    # ---- Layout: where everything sits -------------------------------------
    # Used for drawing AND for working out what was clicked, so they always agree.

    def button_rect(self, number):
        y = PADDING + TITLE_HEIGHT + number * (BUTTON_HEIGHT + BUTTON_GAP)
        return QRectF(PADDING, y, SIDEBAR_WIDTH - PADDING * 2, BUTTON_HEIGHT)

    def tile_grid(self):
        """(left edge, tile width, tile height) of the 2 x 2 grid right of the sidebar."""
        area_width = self.width() - SIDEBAR_WIDTH
        # As big as fits while keeping 16:10, after the fixed parts
        # (padding, title, labels, gaps) are subtracted.
        room_width = (area_width - PADDING * 2 - GAP) / 2
        room_height = (self.height() - PADDING * 2 - TITLE_HEIGHT - LABEL_HEIGHT * 2 - GAP) / 2
        tile_width = min(room_width, room_height * TILE_ASPECT)
        tile_height = tile_width / TILE_ASPECT
        # Centre the grid in its area; any spare width goes to both sides.
        left = SIDEBAR_WIDTH + (area_width - (tile_width * 2 + GAP)) / 2
        return left, tile_width, tile_height

    def tile_rect(self, number):
        left, tile_width, tile_height = self.tile_grid()
        row, column = divmod(number, 2)  # 0 -> (0,0), 1 -> (0,1), 2 -> (1,0), 3 -> (1,1)
        x = left + column * (tile_width + GAP)
        y = PADDING + TITLE_HEIGHT + row * (tile_height + LABEL_HEIGHT + GAP)
        return QRectF(x, y, tile_width, tile_height)

    def target_rect(self, target):
        kind, number = target
        return self.button_rect(number) if kind == "button" else self.tile_rect(number)

    def all_targets(self):
        buttons = [("button", n) for n in range(len(self.buttons))]
        tiles = [("tile", n) for n in range(len(self.recent))]  # only filled tiles
        return buttons + tiles

    def target_at(self, pos):
        for target in self.all_targets():
            if self.target_rect(target).contains(pos):
                return target
        return None

    def activate(self, target):
        kind, number = target
        if kind == "button":
            self.buttons[number][2].emit()
        else:
            self.open_path_requested.emit(self.recent[number][0])

    # ---- Mouse -------------------------------------------------------------

    def showEvent(self, event):
        self.setFocus()  # grab the keyboard as soon as we appear

    def mouseMoveEvent(self, event):
        hovered = self.target_at(event.position())
        if hovered != self.active or self.keyboard_navigating:
            self.active = hovered
            self.keyboard_navigating = False  # the mouse took over
            self.setCursor(Qt.PointingHandCursor if hovered is not None else Qt.ArrowCursor)
            self.update()  # ask Qt to repaint, so the highlight shows

    def leaveEvent(self, event):
        if not self.keyboard_navigating:
            self.active = None
            self.update()

    def mousePressEvent(self, event):
        # Always accept, so clicks on the panel never fall through to the canvas.
        event.accept()
        self.setFocus()
        target = self.target_at(event.position())
        if event.button() == Qt.LeftButton and target is not None:
            self.activate(target)

    def mouseReleaseEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()  # don't zoom the canvas behind the panel

    # ---- Keyboard ----------------------------------------------------------

    def keyPressEvent(self, event):
        moves = {Qt.Key_Up: "up", Qt.Key_Down: "down", Qt.Key_Left: "left", Qt.Key_Right: "right"}
        if event.key() in moves:
            self.active = self.next_target(moves[event.key()])
            self.keyboard_navigating = True
            self.update()
            return  # handled; don't let the canvas pan
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.active is not None:
            self.activate(self.active)
            return
        # Anything else (like Ctrl+V) goes on to the canvas as usual.
        super().keyPressEvent(event)

    def next_target(self, direction):
        """Where an arrow key press leads from the current target."""
        if self.active is None:
            return ("button", 0)  # first press: start at the top of the sidebar

        kind, number = self.active
        button_count, tile_count = len(self.buttons), len(self.recent)

        if kind == "button":
            if direction in ("up", "down"):
                step = 1 if direction == "down" else -1
                # % wraps around: past the last button goes back to the first.
                return ("button", (number + step) % button_count)
            if direction == "right" and tile_count > 0:
                return ("tile", 0)
            return self.active

        # On a tile. Tiles sit in a 2 x 2 grid, numbered 0 1 / 2 3.
        row, column = divmod(number, 2)
        if direction == "left":
            if column == 0:
                return ("button", 0)  # back into the sidebar
            candidate = number - 1
        elif direction == "right":
            candidate = number + 1 if column == 0 else number
        elif direction == "up":
            candidate = number - 2
        else:  # down
            candidate = number + 2
        # Only move if there's actually a board there.
        return ("tile", candidate) if 0 <= candidate < tile_count else self.active

    # ---- Drawing -----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)

        # The panel itself. Shrunk by half a pixel so the 1px border lands
        # exactly on whole pixels and looks crisp.
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), PANEL_RADIUS))

        title_font = QFont(self.font())
        title_font.setPointSizeF(13)
        title_font.setWeight(QFont.DemiBold)
        small_font = QFont(self.font())
        small_font.setPointSizeF(10)

        self.paint_sidebar(painter, title_font, small_font)

        # A thin divider line between the sidebar and the recent boards.
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.drawLine(QPointF(SIDEBAR_WIDTH + 0.5, PADDING), QPointF(SIDEBAR_WIDTH + 0.5, self.height() - PADDING))

        self.paint_recent_boards(painter, title_font, small_font)

    def paint_focus_ring(self, painter, rect, radius):
        """A blue outline just outside `rect`, showing keyboard focus."""
        painter.setPen(QPen(FOCUS_RING_COLOR, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(squircle_path(rect.adjusted(-3, -3, 3, 3), radius + 3))

    def paint_sidebar(self, painter, title_font, small_font):
        painter.setFont(title_font)
        painter.setPen(TITLE_COLOR)
        name_area = QRectF(PADDING, PADDING, SIDEBAR_WIDTH - PADDING * 2, TITLE_HEIGHT)
        painter.drawText(name_area, Qt.AlignLeft | Qt.AlignTop, "refboard")

        painter.setFont(small_font)
        for number, (text, keys, _signal, is_main) in enumerate(self.buttons):
            rect = self.button_rect(number)
            highlighted = self.active == ("button", number)

            # Background: the main button is always blue; the others only
            # get a background while highlighted.
            if is_main:
                painter.setBrush(ACCENT_HOVER_COLOR if highlighted else ACCENT_COLOR)
            elif highlighted:
                painter.setBrush(BUTTON_HOVER_COLOR)
            else:
                painter.setBrush(Qt.NoBrush)
            painter.setPen(Qt.NoPen)
            painter.drawPath(squircle_path(rect, BUTTON_RADIUS))

            if highlighted and self.keyboard_navigating:
                self.paint_focus_ring(painter, rect, BUTTON_RADIUS)

            # Text on the left, the shortcut (e.g. "Ctrl+N") faintly on the right.
            inner = rect.adjusted(12, 0, -12, 0)
            painter.setPen(TITLE_COLOR)
            painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.setPen(TITLE_COLOR if is_main else LABEL_COLOR)
            painter.drawText(inner, Qt.AlignRight | Qt.AlignVCenter, keys.toString(QKeySequence.NativeText))

    def paint_recent_boards(self, painter, title_font, small_font):
        left, tile_width, _tile_height = self.tile_grid()

        # Title, lined up with the left edge of the tiles.
        painter.setFont(title_font)
        painter.setPen(TITLE_COLOR)
        title_area = QRectF(left, PADDING, tile_width * 2 + GAP, TITLE_HEIGHT)
        painter.drawText(title_area, Qt.AlignLeft | Qt.AlignTop, "Recent boards")

        painter.setFont(small_font)
        for number in range(4):
            rect = self.tile_rect(number)
            shape = squircle_path(rect, TILE_RADIUS)

            if number >= len(self.recent):
                # No board for this slot (yet): a dim, empty tile.
                painter.setPen(Qt.NoPen)
                painter.setBrush(EMPTY_TILE_COLOR)
                painter.drawPath(shape)
                continue

            path, preview = self.recent[number]
            highlighted = self.active == ("tile", number)

            painter.setPen(Qt.NoPen)
            painter.setBrush(TILE_COLOR)
            painter.drawPath(shape)
            if preview is not None:
                # Clip to the tile's rounded shape, so the picture gets the
                # same smooth corners. save()/restore() undo the clipping after.
                painter.save()
                painter.setClipPath(shape)
                painter.drawImage(rect, preview)
                painter.restore()

            if highlighted:
                if self.keyboard_navigating:
                    self.paint_focus_ring(painter, rect, TILE_RADIUS)
                else:
                    # Mouse hover: a soft white outline.
                    painter.setPen(QPen(QColor(255, 255, 255, 90), 2))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawPath(shape)

            # The board's name (file name without ".refboard"); "…" if too long.
            painter.setPen(TITLE_COLOR if highlighted else LABEL_COLOR)
            label_area = QRectF(rect.left() + 2, rect.bottom(), rect.width() - 4, LABEL_HEIGHT)
            name = painter.fontMetrics().elidedText(Path(path).stem, Qt.ElideRight, int(label_area.width()))
            painter.drawText(label_area, Qt.AlignLeft | Qt.AlignVCenter, name)
