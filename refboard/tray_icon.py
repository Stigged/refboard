"""The icon in the system tray (the row of small icons next to the clock).

It's the way back when refboard can't be clicked: with click-through on,
every click goes to the window behind it. Clicking the tray icon turns
click-through off and brings refboard to the front; its menu has the
overlay switches too.

The icon is drawn in code, like the panel icons, so there's no image file.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .shapes import squircle_path
from .tool_panel import ACTIVE_COLOR

ICON_SIZES = (16, 22, 24, 32, 48, 64)  # trays differ; give the desktop a choice


def draw_icon(size):
    """The app icon as a picture of size x size pixels."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    paint_icon(painter, size)
    painter.end()
    return pixmap


def paint_icon(painter, size):
    """Paint the app icon: a blue rounded square with two overlapping white
    frames, pictures on a board. (Also used to make the icon files for the
    app menu; see packaging/make_icons.py.)"""
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 20, size / 20)  # draw on a 20 x 20 grid
    painter.setPen(Qt.NoPen)
    painter.setBrush(ACTIVE_COLOR)
    painter.drawPath(squircle_path(QRectF(1, 1, 18, 18), 5))
    pen = QPen(QColor("white"), 1.6)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(QRectF(5, 5, 7, 6))
    painter.setBrush(ACTIVE_COLOR)  # the front frame hides the one behind it
    painter.drawRect(QRectF(8, 9, 7, 6))


def app_icon():
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(draw_icon(size))
    return icon


class TrayIcon(QSystemTrayIcon):
    def __init__(self, window):
        super().__init__(app_icon(), window)
        self.window = window
        self.setToolTip("refboard")

        menu = QMenu()
        self.show_action = self.add(menu, "Show refboard", self.bring_back)
        menu.addSeparator()
        self.pin_action = self.add(menu, "Keep on top", window.toggle_pin, checkable=True)
        self.click_through_action = self.add(menu, "Click-through", window.toggle_click_through,
                                             checkable=True)
        self.add(menu, "Reset opacity", window.canvas.reset_opacity)
        menu.addSeparator()
        self.add(menu, "Quit", window.close)
        # Just before the menu opens, tick the switches that are on.
        menu.aboutToShow.connect(self.refresh)
        self.menu = menu  # keep it alive: the tray only borrows it
        self.setContextMenu(menu)

        self.activated.connect(self.on_activated)

    def add(self, menu, text, method, checkable=False):
        action = QAction(text, menu)
        action.setCheckable(checkable)
        action.triggered.connect(method)
        menu.addAction(action)
        return action

    def refresh(self):
        self.pin_action.setChecked(self.window.pinned)
        self.click_through_action.setChecked(self.window.click_through)

    def on_activated(self, reason):
        # Trigger = a normal (left) click on the icon. Right-click opens the menu.
        if reason == QSystemTrayIcon.Trigger:
            self.bring_back()

    def bring_back(self):
        """Click-through off, and refboard in front again."""
        if self.window.click_through:
            self.window.toggle_click_through()
        self.window.showNormal()  # also undoes minimize
        self.window.raise_()
        self.window.activateWindow()
