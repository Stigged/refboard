"""A frameless window's frame: a thin outline, and resizing from the edges.

refboard's window has no title bar or border (like PureRef), so it can
take up as little room as possible next to your other programs. That
means we have to provide what the border normally gives you:

- An outline, 1 pixel wide, so you can see where the window ends. It's
  faint, and brightens when the mouse is close enough to an edge to resize.
- Resizing: a few pixels along every edge (a bit more at the corners) are
  an invisible grab zone. Hovering there shows a resize cursor; dragging
  resizes the window.

(Moving the window is Alt+drag on the canvas; see Canvas.mousePressEvent.)
"""

from PySide6.QtCore import QEvent, QObject, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QApplication, QWidget

from .platform_support import start_window_resize

EDGE_GRAB = 6  # how close to an edge (in pixels) the mouse must be to resize
CORNER_GRAB = 16  # near a corner, resize both ways from this far along the edge
OUTLINE_COLOR = QColor(255, 255, 255, 28)  # faint white
OUTLINE_HOVER_COLOR = QColor(255, 255, 255, 110)  # mouse is in a grab zone

# Which cursor to show for which edges.
CURSORS = {
    frozenset({"left"}): Qt.SizeHorCursor,
    frozenset({"right"}): Qt.SizeHorCursor,
    frozenset({"top"}): Qt.SizeVerCursor,
    frozenset({"bottom"}): Qt.SizeVerCursor,
    frozenset({"left", "top"}): Qt.SizeFDiagCursor,
    frozenset({"right", "bottom"}): Qt.SizeFDiagCursor,
    frozenset({"right", "top"}): Qt.SizeBDiagCursor,
    frozenset({"left", "bottom"}): Qt.SizeBDiagCursor,
}


class WindowOutline(QWidget):
    """The 1 pixel line around the window. It lies on top of everything
    else but lets every click through, so it's only something to look at."""

    def __init__(self, window):
        super().__init__(window)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.bright = False
        window.installEventFilter(self)  # to follow the window's size
        self.setGeometry(window.rect())
        self.raise_()

    def set_bright(self, bright):
        if bright != self.bright:
            self.bright = bright
            self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
            self.raise_()  # stay on top of anything added to the window since
        return False  # only looking; the window still handles the event

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(OUTLINE_HOVER_COLOR if self.bright else OUTLINE_COLOR, 1))
        # A 1 pixel line is drawn centred on its path, so go half a pixel in
        # to keep it fully inside the window.
        painter.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))


class WindowFrame(QObject):
    """Watches the mouse over the whole window (canvas, panels, everything)
    and takes over presses that land in a grab zone along the edges."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.outline = WindowOutline(window)
        self.cursor_shown = False  # is our resize cursor showing right now?
        # Set while we resize the window ourselves (only where the system
        # can't, see start_window_resize).
        self.manual_resize = None
        # Mouse events go to whichever widget is under the mouse, so to see
        # them all we watch the whole application.
        QApplication.instance().installEventFilter(self)

    def edges_at(self, pos):
        """Which edges a point (in window coordinates) is close enough to grab."""
        if self.window.isMaximized() or self.window.isFullScreen():
            return set()
        w, h = self.window.width(), self.window.height()
        x, y = pos.x(), pos.y()
        edges = set()
        if x < EDGE_GRAB:
            edges.add("left")
        elif x >= w - EDGE_GRAB:
            edges.add("right")
        if y < EDGE_GRAB:
            edges.add("top")
        elif y >= h - EDGE_GRAB:
            edges.add("bottom")
        # Near a corner, grab both edges, so corners are easier to hit.
        if edges & {"left", "right"}:
            if y < CORNER_GRAB:
                edges.add("top")
            elif y >= h - CORNER_GRAB:
                edges.add("bottom")
        if edges & {"top", "bottom"}:
            if x < CORNER_GRAB:
                edges.add("left")
            elif x >= w - CORNER_GRAB:
                edges.add("right")
        return edges

    def show_hover(self, edges):
        """Resize cursor and bright outline while in a grab zone; normal otherwise.

        The cursor is an "override cursor": it wins over whatever cursor the
        widget under the mouse wants, like the canvas's hand cursors.
        """
        self.outline.set_bright(bool(edges))
        if edges:
            cursor = CURSORS[frozenset(edges)]
            if self.cursor_shown:
                QApplication.changeOverrideCursor(cursor)
            else:
                QApplication.setOverrideCursor(cursor)
                self.cursor_shown = True
        elif self.cursor_shown:
            QApplication.restoreOverrideCursor()
            self.cursor_shown = False

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in (QEvent.MouseMove, QEvent.MouseButtonPress,
                        QEvent.MouseButtonRelease, QEvent.Leave):
            return False  # quick way out: we get every event in the app
        if not isinstance(watched, QWidget) or watched.window() is not self.window:
            return False  # another window, like a menu or a dialog

        if kind == QEvent.Leave:
            if watched is self.window:  # the mouse left the window
                self.show_hover(set())
            return False

        if self.manual_resize is not None:
            return self.continue_manual_resize(event)

        edges = self.edges_at(self.window.mapFromGlobal(event.globalPosition().toPoint()))
        if kind == QEvent.MouseMove and event.buttons() == Qt.NoButton:
            self.show_hover(edges)
            return False  # the widget under the mouse still sees the move
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and edges:
            if not start_window_resize(self.window, edges):
                self.manual_resize = {
                    "edges": edges,
                    "start_mouse": event.globalPosition().toPoint(),
                    "start_geometry": self.window.geometry(),
                }
            return True  # ours: the canvas shouldn't start a selection box too
        return False

    def continue_manual_resize(self, event):
        """Resize the window ourselves, following the mouse."""
        if event.type() == QEvent.MouseButtonRelease:
            self.manual_resize = None
            return True
        if event.type() != QEvent.MouseMove:
            return True
        resize = self.manual_resize
        delta = event.globalPosition().toPoint() - resize["start_mouse"]
        start: QRect = resize["start_geometry"]
        left, top, right, bottom = start.left(), start.top(), start.right(), start.bottom()
        minimum = self.window.minimumSize()
        # Move the grabbed edges, but never past the smallest allowed size.
        if "left" in resize["edges"]:
            left = min(left + delta.x(), right + 1 - minimum.width())
        if "right" in resize["edges"]:
            right = max(right + delta.x(), left - 1 + minimum.width())
        if "top" in resize["edges"]:
            top = min(top + delta.y(), bottom + 1 - minimum.height())
        if "bottom" in resize["edges"]:
            bottom = max(bottom + delta.y(), top - 1 + minimum.height())
        self.window.setGeometry(QRect(left, top, right - left + 1, bottom - top + 1))
        return True
