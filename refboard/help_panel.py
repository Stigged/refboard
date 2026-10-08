"""The welcome panel (first start) and the shortcuts panel (F1).

Both show the same list of shortcuts. The welcome panel adds a short
introduction and a "Get started" button, and only appears the very first
time refboard starts. After that, F1 (or "Shortcuts" in the menu) shows the
list without the welcome.
"""

from html import escape

from PySide6.QtCore import QEvent, QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QLabel, QPushButton, QScrollArea, QWidget,
)

from .platform_support import IS_MACOS, delete_shortcut_text, shortcut_text
from .shapes import squircle_path
from .start_panel import ACCENT_COLOR, ACCENT_HOVER_COLOR, BORDER_COLOR, LABEL_COLOR, PANEL_COLOR, TITLE_COLOR

WELCOME_SETTING = "welcome_shown"  # in QSettings: has the welcome been clicked away?
PANEL_WIDTH = 860  # the most room the panel takes; it shrinks in small windows
PANEL_HEIGHT = 680
WINDOW_MARGIN = 16  # room kept between the panel and the window's edges
PADDING = 28
RADIUS = 28
TWO_COLUMNS_FROM = 640  # narrower than this (in pixels): one column of shortcuts
BUTTON_HEIGHT = 36
TITLE_HEIGHT = 40  # the title's line, next to the close button
SCROLLBAR_WIDTH = 8

# Mouse combinations are written with the key names of this system.
CTRL = "⌘" if IS_MACOS else "Ctrl"
ALT = "⌥" if IS_MACOS else "Alt"
SHIFT = "⇧" if IS_MACOS else "Shift"


def k(keys):
    """A keyboard shortcut as this system writes it (Ctrl+C is ⌘C on a Mac)."""
    return shortcut_text(keys)


# Every shortcut and mouse action, in groups: (heading, [(what, how)]).
SECTIONS = [
    ("Images in", [
        ("Add images", "Drag them onto the board"),
        ("Paste an image or text", k("Ctrl+V")),
    ]),
    ("Moving around", [
        ("Pan", "Middle-drag, or Space + drag"),
        ("Zoom", "Scroll"),
        ("Fit everything in view", "F"),
    ]),
    ("Selecting and arranging", [
        ("Select", f"Click, or drag a box ({CTRL} adds)"),
        ("Select all", k("Ctrl+A")),
        ("Move", f"Drag ({SHIFT}: no snapping)"),
        ("Scale", f"Drag a corner, or {CTRL} + scroll"),
        ("Rotate", f"Drag just outside a corner, or {ALT} + scroll"),
        ("Arrange in rows", "A"),
        ("Forward / backward", "] / ["),
        ("To front / to back", f"{k('Ctrl+]')} / {k('Ctrl+[')}"),
    ]),
    ("Editing", [
        ("Crop", f"C, or {CTRL} + drag an edge"),
        ("Flip", "H / V"),
        ("Black and white", "G"),
        ("Text note", "T"),
        ("Copy / duplicate", f"{k('Ctrl+C')} / {k('Ctrl+D')}"),
        ("Delete", delete_shortcut_text()),
        ("Undo / redo", f"{k('Ctrl+Z')} / {k('Ctrl+Shift+Z')}"),
        ("More options", "Right-click"),
    ]),
    ("Overlay", [
        ("Click-through on / off", f"{k('Ctrl+T')} (Esc also ends it)"),
        ("Background opacity", "O"),
        ("Window opacity", k("Shift+O")),
        ("Reset opacity", k("Ctrl+Shift+O")),
        ("Keep on top", "Pin button, bottom panel"),
        ("Move the window", f"{ALT} + drag"),
        ("Resize the window", "Drag its edges"),
    ]),
    ("Boards", [
        ("Menu", "Esc"),
        ("New / open", f"{k('Ctrl+N')} / {k('Ctrl+O')}"),
        ("Save / save as", f"{k('Ctrl+S')} / {k('Ctrl+Shift+S')}"),
        ("These shortcuts", "F1"),
        ("Close refboard", k("Ctrl+W")),
    ]),
]

WELCOME_TEXT = (
    "refboard keeps your reference images together on one endless board. "
    "Drop or paste them in, arrange them, and float the board over the "
    "program you're working in. Your boards are saved with the images inside."
)


def welcome_shown():
    return QSettings("refboard", "refboard").value(WELCOME_SETTING, False, type=bool)


def remember_welcome_shown():
    QSettings("refboard", "refboard").setValue(WELCOME_SETTING, True)


def color(c):
    return c.name()


class HelpPanel(QWidget):
    """A card in the middle of the canvas with the list of shortcuts.
    Closes with Esc, the × in the corner, a click next to it, or (as the
    welcome) the "Get started" button."""

    closed = Signal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.welcome = False
        self.columns = 2

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(48)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(0, 0, 0, 150))
        self.setGraphicsEffect(shadow)

        self.title = QLabel(self)
        self.title.setStyleSheet(f"color: {color(TITLE_COLOR)}; font-size: 17pt; font-weight: 600;"
                                 "background: transparent;")

        # The text sits in a scroll area, for windows too small to show it all.
        self.text = QLabel()
        self.text.setTextFormat(Qt.RichText)
        self.text.setWordWrap(True)
        self.text.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.text.setStyleSheet("background: transparent;")
        self.scroll = QScrollArea(self)
        self.scroll.setWidget(self.text)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"""
            QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
            QScrollBar::handle:vertical {{ background: {color(BORDER_COLOR)}; border-radius: 4px; min-height: 30px; }}
            QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
                background: none; height: 0; }}
        """)

        self.close_button = QPushButton("✕", self)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setFixedSize(32, 32)
        self.close_button.setToolTip("Close  (Esc)")
        self.close_button.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {color(LABEL_COLOR)}; border: none;
                           border-radius: 10px; font-size: 15px; }}
            QPushButton:hover {{ background: {color(BORDER_COLOR)}; color: {color(TITLE_COLOR)}; }}
        """)
        self.close_button.clicked.connect(self.close_panel)

        self.start_button = QPushButton("Get started", self)
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.setFixedHeight(BUTTON_HEIGHT)
        self.start_button.setStyleSheet(f"""
            QPushButton {{ background: {color(ACCENT_COLOR)}; color: white; border: none;
                           border-radius: 10px; padding: 0 22px; font-weight: 600; }}
            QPushButton:hover {{ background: {color(ACCENT_HOVER_COLOR)}; }}
        """)
        self.start_button.clicked.connect(self.close_panel)

        self.setFocusPolicy(Qt.StrongFocus)
        canvas.installEventFilter(self)  # to follow the window's size
        self.hide()

    def open(self, welcome=False):
        self.welcome = welcome
        self.start_button.setVisible(welcome)
        self.place()
        self.lay_out()  # now, not later: Qt delays resize events while we're hidden
        self.fill_text()
        self.scroll.verticalScrollBar().setValue(0)
        self.show()
        self.raise_()
        self.setFocus()

    def close_panel(self):
        if not self.isVisible():
            return
        self.hide()
        if self.welcome:
            remember_welcome_shown()
        self.closed.emit()

    # ---- Size and layout -------------------------------------------------------

    def place(self):
        """As big as PANEL_WIDTH x PANEL_HEIGHT, smaller if the window is;
        centred in the canvas."""
        width = min(PANEL_WIDTH, self.canvas.width() - WINDOW_MARGIN * 2)
        height = min(PANEL_HEIGHT, self.canvas.height() - WINDOW_MARGIN * 2)
        self.setGeometry((self.canvas.width() - width) // 2, (self.canvas.height() - height) // 2,
                         width, height)

    def resizeEvent(self, event):
        self.lay_out()

    def lay_out(self):
        """Put the title, text, close button and "Get started" in place."""
        bottom = PADDING
        if self.welcome:
            self.start_button.adjustSize()
            bottom += BUTTON_HEIGHT + 16
            self.start_button.move(self.width() - PADDING - self.start_button.width(),
                                   self.height() - PADDING - BUTTON_HEIGHT)
        self.close_button.move(self.width() - PADDING + 6 - self.close_button.width(),
                               PADDING + (TITLE_HEIGHT - self.close_button.height()) // 2)
        self.title.setGeometry(PADDING, PADDING, self.width() - PADDING * 2 - 40, TITLE_HEIGHT)
        top = PADDING + TITLE_HEIGHT + 8
        self.scroll.setGeometry(PADDING, top, self.width() - PADDING * 2 + 8, self.height() - top - bottom)
        columns = 2 if self.width() >= TWO_COLUMNS_FROM else 1
        if columns != self.columns:
            self.columns = columns
            self.fill_text()
        self.fit_text()

    def fit_text(self):
        """Make the text exactly as tall as it needs to be at this width.

        Left alone, Qt reserves room for wrapped text as if it were
        squeezed into a narrow strip, which adds a lot of empty space at
        the bottom to scroll through.
        """
        # The width the text gets: the scroll area minus its scrollbar.
        # (Asked from our own numbers: the scroll area may not have caught
        # up with a new size yet.)
        width = self.scroll.width() - SCROLLBAR_WIDTH
        self.text.setMinimumHeight(0)  # or Qt counts the old minimum in its answer
        height = self.text.heightForWidth(width)
        if height > 0:  # not yet known (-1) before the panel has a size
            self.text.setMinimumHeight(height)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize and self.isVisible():
            self.place()
        return False

    # ---- The text ------------------------------------------------------------

    def fill_text(self):
        self.title.setText("Welcome to RefBoard!" if self.welcome else "Shortcuts")
        parts = []
        if self.welcome:
            parts.append(f'<p style="color: {color(TITLE_COLOR)}; font-size: 11pt; margin-top: 0;">'
                         f'{escape(WELCOME_TEXT)}</p>'
                         f'<p style="color: {color(LABEL_COLOR)}; margin-bottom: 6px;">Here are the basics. '
                         f'You can find this list again any time with F1, or in the menu (Esc).</p>')
        # The sections side by side in columns. Each section goes into the
        # column that's shortest so far, so the columns end up about even.
        columns = [[] for _ in range(self.columns)]
        lengths = [0] * self.columns
        for section in SECTIONS:
            shortest = lengths.index(min(lengths))
            columns[shortest].append(section)
            lengths[shortest] += len(section[1]) + 2  # + 2: room for the heading
        cells = "".join(
            f'<td width="{100 // self.columns}%" valign="top" style="padding-right: 24px;">'
            + "".join(self.section_html(section) for section in column) + "</td>"
            for column in columns)
        parts.append(f'<table width="100%" cellspacing="0" cellpadding="0"><tr>{cells}</tr></table>')
        self.text.setText("".join(parts))
        self.fit_text()

    def section_html(self, section):
        heading, rows = section
        html = (f'<div style="color: {color(ACCENT_HOVER_COLOR)}; font-weight: 600; '
                f'margin-top: 14px; margin-bottom: 4px;">{escape(heading)}</div>'
                '<table width="100%" cellspacing="0" cellpadding="2">')
        for what, how in rows:
            html += (f'<tr><td style="color: {color(LABEL_COLOR)};">{escape(what)}</td>'
                     f'<td align="right" style="color: {color(TITLE_COLOR)};">{escape(how)}</td></tr>')
        return html + "</table>"

    # ---- Input and drawing -------------------------------------------------------

    def mousePressEvent(self, event):
        event.accept()  # clicks on the panel never reach the canvas

    def wheelEvent(self, event):
        event.accept()  # scrolling the list doesn't zoom the board behind it

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(BORDER_COLOR, 1))
        painter.setBrush(PANEL_COLOR)
        painter.drawPath(squircle_path(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), RADIUS))
