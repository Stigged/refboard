"""The start panel: a floating card with a sidebar (new / open) and your recent boards.

The recent-board tiles are still placeholders; filling them comes later.
"""

import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

# Colors: Apple dark-mode "elevated" grays.
PANEL_COLOR = QColor("#2C2C2E")
BORDER_COLOR = QColor("#3A3A3C")
TILE_COLOR = QColor("#3A3A3C")
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
    """Floats in the middle of its parent (the canvas) and stays centred."""

    # Wires for the window to connect to: "the user wants a new board / to open one".
    new_board_requested = Signal()
    open_requested = Signal()

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
        # The highlighted button (by mouse hover or arrow keys), or None.
        self.active = None
        # True while using the arrow keys: then we also draw a focus ring.
        self.keyboard_navigating = False
        self.setMouseTracking(True)  # get mouse moves even without a button held
        # Accept keyboard focus, so arrow keys come to us instead of the canvas.
        self.setFocusPolicy(Qt.StrongFocus)

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

    # ---- Sidebar buttons ---------------------------------------------------

    def button_rect(self, number):
        """Where button `number` sits. Used both for drawing and for clicking."""
        y = PADDING + TITLE_HEIGHT + number * (BUTTON_HEIGHT + BUTTON_GAP)
        return QRectF(PADDING, y, SIDEBAR_WIDTH - PADDING * 2, BUTTON_HEIGHT)

    def button_at(self, pos):
        for number in range(len(self.buttons)):
            if self.button_rect(number).contains(pos):
                return number
        return None

    def showEvent(self, event):
        self.setFocus()  # grab the keyboard as soon as we appear

    def mouseMoveEvent(self, event):
        hovered = self.button_at(event.position())
        if hovered != self.active or self.keyboard_navigating:
            self.active = hovered
            self.keyboard_navigating = False  # the mouse took over
            self.setCursor(Qt.PointingHandCursor if hovered is not None else Qt.ArrowCursor)
            self.update()  # ask Qt to repaint, so the highlight shows

    def leaveEvent(self, event):
        if not self.keyboard_navigating:
            self.active = None
            self.update()

    def keyPressEvent(self, event):
        count = len(self.buttons)
        if event.key() in (Qt.Key_Down, Qt.Key_Up):
            step = 1 if event.key() == Qt.Key_Down else -1
            if self.active is None:
                # First press: start at the top (Down) or the bottom (Up).
                self.active = 0 if step == 1 else count - 1
            else:
                # % count wraps around: past the last button goes back to the first.
                self.active = (self.active + step) % count
            self.keyboard_navigating = True
            self.update()
            return  # handled; don't let the canvas pan
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.active is not None:
            self.buttons[self.active][2].emit()
            return
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            return  # swallow these too, for now (later: move into the tiles)
        # Anything else (like Ctrl+V) goes on to the canvas as usual.
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Always accept, so clicks on the panel never fall through to the canvas.
        event.accept()
        number = self.button_at(event.position())
        self.setFocus()
        if event.button() == Qt.LeftButton and number is not None:
            signal = self.buttons[number][2]
            signal.emit()

    def mouseReleaseEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()  # don't zoom the canvas behind the panel

    # ---- Drawing -----------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

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

    def paint_sidebar(self, painter, title_font, small_font):
        painter.setFont(title_font)
        painter.setPen(TITLE_COLOR)
        name_area = QRectF(PADDING, PADDING, SIDEBAR_WIDTH - PADDING * 2, TITLE_HEIGHT)
        painter.drawText(name_area, Qt.AlignLeft | Qt.AlignTop, "refboard")

        painter.setFont(small_font)
        for number, (text, keys, _signal, is_main) in enumerate(self.buttons):
            rect = self.button_rect(number)
            hovered = number == self.active

            # Background: the main button is always blue; the others only
            # get a background while hovered.
            if is_main:
                painter.setBrush(ACCENT_HOVER_COLOR if hovered else ACCENT_COLOR)
            elif hovered:
                painter.setBrush(BUTTON_HOVER_COLOR)
            else:
                painter.setBrush(Qt.NoBrush)
            painter.setPen(Qt.NoPen)
            painter.drawPath(squircle_path(rect, BUTTON_RADIUS))

            # Keyboard focus ring: an outline drawn just outside the button.
            if hovered and self.keyboard_navigating:
                ring = QPen(FOCUS_RING_COLOR, 2)
                painter.setPen(ring)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(squircle_path(rect.adjusted(-3, -3, 3, 3), BUTTON_RADIUS + 3))

            # Text on the left, the shortcut (e.g. "Ctrl+N") faintly on the right.
            inner = rect.adjusted(12, 0, -12, 0)
            painter.setPen(TITLE_COLOR)
            painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, text)
            painter.setPen(TITLE_COLOR if is_main else LABEL_COLOR)
            painter.drawText(inner, Qt.AlignRight | Qt.AlignVCenter, keys.toString(QKeySequence.NativeText))

    def paint_recent_boards(self, painter, title_font, small_font):
        # Everything right of the sidebar.
        area_left = SIDEBAR_WIDTH
        area_width = self.width() - SIDEBAR_WIDTH

        # Tile size: as big as fits while keeping 16:10. The fixed parts
        # (padding, title, labels, gaps) are subtracted first.
        room_width = (area_width - PADDING * 2 - GAP) / 2
        room_height = (self.height() - PADDING * 2 - TITLE_HEIGHT - LABEL_HEIGHT * 2 - GAP) / 2
        tile_width = min(room_width, room_height * TILE_ASPECT)
        tile_height = tile_width / TILE_ASPECT
        # Centre the 2 x 2 grid in its area; any spare width goes to both sides.
        grid_width = tile_width * 2 + GAP
        left = area_left + (area_width - grid_width) / 2

        # Title, lined up with the left edge of the tiles.
        painter.setFont(title_font)
        painter.setPen(TITLE_COLOR)
        title_area = QRectF(left, PADDING, grid_width, TITLE_HEIGHT)
        painter.drawText(title_area, Qt.AlignLeft | Qt.AlignTop, "Recent boards")

        # Four tiles in a 2 x 2 grid.
        painter.setFont(small_font)
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
