"""Start refboard. Run with:  .venv/bin/python main.py  [optional: a .refboard file]"""

import sys
from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from board_file import FILE_EXTENSION, BoardFileError, load_board, save_board
from canvas import Canvas

FILE_FILTER = f"refboard boards (*{FILE_EXTENSION})"


class MainWindow(QMainWindow):
    """The window around the canvas. Handles files: open, save, and the title bar."""

    def __init__(self):
        super().__init__()
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self.resize(1000, 700)

        self.path = None  # the file this board was opened from / saved to
        # Connect the canvas's "changed" signal to our method: every time the
        # board changes, Qt calls self.mark_unsaved for us.
        self.canvas.changed.connect(self.mark_unsaved)

        self.add_shortcut(QKeySequence.Save, self.save)  # Ctrl+S
        self.add_shortcut(QKeySequence.SaveAs, self.save_as)  # Ctrl+Shift+S
        self.add_shortcut(QKeySequence.Open, self.open)  # Ctrl+O

        self.update_title()

    def add_shortcut(self, keys, method):
        """Run `method` when `keys` are pressed anywhere in the window."""
        action = QAction(self)
        action.setShortcut(keys)
        action.triggered.connect(method)
        self.addAction(action)

    # ---- Title bar and unsaved changes -------------------------------------

    def update_title(self):
        name = Path(self.path).name if self.path else "Untitled"
        # Qt replaces "[*]" with "*" while the window is marked as modified.
        self.setWindowTitle(f"{name}[*] — refboard")

    def mark_unsaved(self):
        self.setWindowModified(True)

    def ok_to_lose_changes(self):
        """Ask what to do with unsaved changes. Returns False if the user cancels."""
        if not self.isWindowModified():
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved changes",
            "This board has unsaved changes. Save them first?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        )
        if answer == QMessageBox.Save:
            return self.save()
        return answer == QMessageBox.Discard

    def closeEvent(self, event):
        # Qt calls this when the window is about to close. ignore() = stay open.
        if self.ok_to_lose_changes():
            event.accept()
        else:
            event.ignore()

    # ---- Open and save -----------------------------------------------------

    def open(self):
        if not self.ok_to_lose_changes():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open board", "", FILE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path):
        try:
            load_board(path, self.canvas)
        except BoardFileError as error:
            QMessageBox.warning(self, "Couldn't open board", str(error))
            return
        self.path = path
        self.setWindowModified(False)
        self.update_title()

    def save(self):
        """Save to the current file (or ask for one). Returns True if it was saved."""
        if self.path is None:
            return self.save_as()
        try:
            save_board(self.path, self.canvas)
        except OSError as error:
            QMessageBox.warning(self, "Couldn't save board", str(error))
            return False
        self.setWindowModified(False)
        return True

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save board", "", FILE_FILTER)
        if not path:
            return False  # the user pressed Cancel
        if not path.endswith(FILE_EXTENSION):
            path += FILE_EXTENSION
        self.path = path
        self.update_title()
        return self.save()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("refboard")

    window = MainWindow()
    window.show()
    # Started as "main.py some_board.refboard"? Then open that board.
    if len(sys.argv) > 1:
        window.open_path(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
