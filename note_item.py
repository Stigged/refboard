"""A text note on the board: a small piece of text on a dark card."""

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPen, QTextCursor
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsTextItem, QStyle

from board_item import ACCENT_COLOR, BoardItem

NOTE_TEXT_COLOR = QColor("#E5E5EA")
NOTE_BACKGROUND = QColor(44, 44, 46, 235)  # Apple "#2C2C2E", a tiny bit see-through
NOTE_FONT_SIZE = 20  # in pixels, when the note is at 100% and the board at 100%
NOTE_PADDING = 10  # room between the text and the edge of the card


class NoteItem(BoardItem, QGraphicsTextItem):
    """Text you can move, scale, rotate and stack like an image.

    Double-click to type in it. Typing ends with Esc or by clicking
    somewhere else; the canvas hears about that through `editing_finished`.
    """

    editing_finished = Signal()

    def __init__(self, text=""):
        super().__init__()
        font = QFont()
        font.setPixelSize(NOTE_FONT_SIZE)
        self.setFont(font)
        self.setDefaultTextColor(NOTE_TEXT_COLOR)
        self.document().setDocumentMargin(NOTE_PADDING)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable)
        # Whenever the text changes size (typing), re-centre the turning point.
        self.document().documentLayout().documentSizeChanged.connect(self.keep_in_place)
        self.setPlainText(text)
        self.keep_in_place()

    def local_rect(self):
        """The whole card, in the note's own units."""
        return self.boundingRect()

    def keep_in_place(self):
        """Scale and rotate around the middle of the card, like images do.

        The middle moves when the text grows, which would make a rotated
        note jump. So, like ImageItem.set_crop, we pin the card's (0, 0)
        corner to the same spot on the canvas.
        """
        before = self.mapToScene(QPointF(0, 0))
        self.setTransformOriginPoint(self.local_rect().center())
        self.setPos(self.pos() + before - self.mapToScene(QPointF(0, 0)))

    # ---- Undo, duplicate ---------------------------------------------------

    def state(self):
        return (self.pos(), self.scale(), self.rotation(), self.zValue(), self.toPlainText())

    def set_state(self, state):
        pos, scale, rotation, z, text = state
        if text != self.toPlainText():
            self.setPlainText(text)
        self.setPos(pos)
        self.setScale(scale)
        self.setRotation(rotation)
        self.setZValue(z)

    def clone(self):
        copy = NoteItem(self.toPlainText())
        copy.set_state(self.state())
        return copy

    # ---- Typing ------------------------------------------------------------

    def is_editing(self):
        return bool(self.textInteractionFlags() & Qt.TextEditorInteraction)

    def start_editing(self):
        self.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.setFocus()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)  # start typing at the end
        self.setTextCursor(cursor)

    def stop_editing(self):
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.clearFocus()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Switching to another window, or opening a menu, doesn't end typing.
        if self.is_editing() and event.reason() not in (Qt.ActiveWindowFocusReason, Qt.PopupFocusReason):
            self.editing_finished.emit()

    def keyPressEvent(self, event):
        # Paste as plain text: otherwise text copied from a web page keeps
        # its fonts and colors.
        if event.matches(QKeySequence.Paste):
            cursor = self.textCursor()
            cursor.insertText(QApplication.clipboard().text())
            self.setTextCursor(cursor)
            return
        super().keyPressEvent(event)

    # ---- Drawing -----------------------------------------------------------

    def paint(self, painter, option, widget=None):
        # Hide Qt's dotted boxes; we draw our own selection.
        option.state &= ~QStyle.State_Selected
        option.state &= ~QStyle.State_HasFocus

        painter.setPen(Qt.NoPen)
        painter.setBrush(NOTE_BACKGROUND)
        painter.drawRect(self.local_rect())

        super().paint(painter, option, widget)

        if self.isSelected():
            self.paint_selection(painter)
        elif self.is_editing():
            # A thin blue line shows you're typing in this note.
            outline = QPen(ACCENT_COLOR, 1.5)
            outline.setCosmetic(True)
            painter.setPen(outline)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.local_rect())
