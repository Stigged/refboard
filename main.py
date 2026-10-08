"""Start refboard. Run with:  .venv/bin/python main.py  [optional: a .refboard file]"""

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QMainWindow, QMessageBox

from backup import backup_path, forget, left_behind, release, remove_backup
from board_file import FILE_EXTENSION, BoardFileError, load_board, read_preview, save_board
from canvas import Canvas
from recent import add_recent_board, recent_boards, remove_recent_board
from start_panel import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, StartPanel
from tool_panel import ToolPanel

FILE_FILTER = f"refboard boards (*{FILE_EXTENSION})"
# Once the start panel is closed, the window may get this small.
SMALLEST_WINDOW_WIDTH = 200
SMALLEST_WINDOW_HEIGHT = 150
BACKUP_SECONDS = 30  # after a change, a crash backup is written within this many seconds


class MainWindow(QMainWindow):
    """The window around the canvas. Handles files: open, save, and the title bar."""

    def __init__(self):
        super().__init__()
        self.canvas = Canvas()
        self.setCentralWidget(self.canvas)
        self.resize(1000, 700)
        # While the start panel shows, the window must be big enough for it.
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.path = None  # the file this board was opened from / saved to
        # Connect the canvas's "changed" signal to our method: every time the
        # board changes, Qt calls self.mark_unsaved for us.
        self.canvas.changed.connect(self.mark_unsaved)

        # Crash backups (see backup.py). The first change starts a 30 second
        # countdown; when it runs out, the board is backed up. Changes during
        # the countdown don't restart it, so you never lose more than that.
        self.backup_timer = QTimer(self)
        self.backup_timer.setSingleShot(True)
        self.backup_timer.setInterval(BACKUP_SECONDS * 1000)
        self.backup_timer.timeout.connect(self.write_backup)
        self.canvas.changed.connect(self.schedule_backup)

        # The tool panel on the left edge; hidden while the start panel shows.
        self.tool_panel = ToolPanel(self.canvas)
        self.tool_panel.hide()

        # The recent-boards panel floats over the canvas until you start working.
        self.start_panel = StartPanel(self.canvas)
        self.canvas.changed.connect(self.close_start_panel)
        self.start_panel.new_board_requested.connect(self.new_board)
        self.start_panel.open_requested.connect(self.open)
        self.start_panel.open_path_requested.connect(self.open_recent)
        self.refresh_recent()

        self.add_shortcut(QKeySequence.New, self.new_board)  # Ctrl+N
        self.add_shortcut(QKeySequence.Save, self.save)  # Ctrl+S
        self.add_shortcut(QKeySequence.SaveAs, self.save_as)  # Ctrl+Shift+S
        self.add_shortcut(QKeySequence.Open, self.open)  # Ctrl+O
        self.add_shortcut(QKeySequence(Qt.Key_Escape), self.close_start_panel)

        self.update_title()

    def close_start_panel(self):
        """Hide the start panel and let the window shrink again (handy for a
        small reference window in a screen corner)."""
        self.start_panel.hide()
        self.tool_panel.show()
        self.setMinimumSize(SMALLEST_WINDOW_WIDTH, SMALLEST_WINDOW_HEIGHT)
        self.canvas.setFocus()  # give the keyboard back to the canvas

    def refresh_recent(self):
        """Give the start panel the current list of recent boards, with previews."""
        self.start_panel.set_recent([(path, read_preview(path)) for path in recent_boards()])

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

    def mark_saved(self):
        """The board matches its file (or is a fresh empty one): no backup needed."""
        self.setWindowModified(False)
        self.backup_timer.stop()
        remove_backup()

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
            release()  # closing normally: nothing to recover next time
            event.accept()
        else:
            event.ignore()

    # ---- Open and save -----------------------------------------------------

    def new_board(self):
        if not self.ok_to_lose_changes():
            return
        self.canvas.clear_board()
        self.path = None
        self.mark_saved()
        self.update_title()
        self.close_start_panel()

    def open(self):
        if not self.ok_to_lose_changes():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open board", "", FILE_FILTER)
        if path:
            self.open_path(path)

    def open_recent(self, path):
        if self.ok_to_lose_changes():
            self.open_path(path)

    def open_path(self, path):
        try:
            load_board(path, self.canvas)
        except BoardFileError as error:
            QMessageBox.warning(self, "Couldn't open board", str(error))
            # Broken or gone? Then it shouldn't stay in the recent list.
            remove_recent_board(path)
            self.refresh_recent()
            return
        self.path = path
        self.mark_saved()
        self.update_title()
        self.close_start_panel()
        add_recent_board(path)

    def save(self):
        """Save to the current file (or ask for one). Returns True if it was saved."""
        if self.path is None:
            return self.save_as()
        try:
            save_board(self.path, self.canvas)
        except OSError as error:
            QMessageBox.warning(self, "Couldn't save board", str(error))
            return False
        self.mark_saved()
        add_recent_board(self.path)
        return True

    def save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save board", "", FILE_FILTER)
        if not path:
            return False  # the user pressed Cancel
        # lower(): Windows and macOS treat "Board.REFBOARD" as the same extension.
        if not path.lower().endswith(FILE_EXTENSION):
            path += FILE_EXTENSION
        self.path = path
        self.update_title()
        return self.save()

    # ---- Crash backups -----------------------------------------------------

    def schedule_backup(self):
        if not self.backup_timer.isActive():
            self.backup_timer.start()

    def write_backup(self):
        if not self.isWindowModified():
            return  # saved in the meantime: the real file is up to date
        try:
            # No preview picture: it isn't needed, and skipping it is quicker.
            save_board(backup_path(), self.canvas, extra={"original_path": self.path}, preview=False)
        except OSError:
            pass  # a failed backup shouldn't interrupt your work; we'll try again next time

    def offer_recovery(self):
        """If refboard crashed last time, offer to bring the board back.
        Returns True if a board was restored."""
        backups = left_behind()
        if not backups:
            return False
        path, lock = backups[0]  # the newest
        for _older, older_lock in backups[1:]:
            older_lock.unlock()  # leave those for next time
        when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        box = QMessageBox(self)
        box.setWindowTitle("Restore board?")
        box.setText("refboard didn't close properly last time.")
        box.setInformativeText(f"A backup of your board from {when} was found. Restore it?")
        restore = box.addButton("Restore", QMessageBox.AcceptRole)
        box.addButton("Discard", QMessageBox.DestructiveRole)
        box.setDefaultButton(restore)
        box.exec()

        if box.clickedButton() is not restore:
            forget(path, lock)
            return False
        try:
            board = load_board(path, self.canvas)
        except BoardFileError as error:
            QMessageBox.warning(self, "Couldn't restore board", str(error))
            forget(path, lock)
            return False
        # Back to how it was: same file name in the title, still unsaved.
        self.path = board.get("original_path")
        self.update_title()
        self.close_start_panel()
        self.setWindowModified(True)
        # Our own backup replaces the old one, so a second crash loses nothing either.
        self.write_backup()
        forget(path, lock)
        return True


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("refboard")

    window = MainWindow()
    window.show()
    # Crashed last time? Offer the backup first. Otherwise, if started as
    # "main.py some_board.refboard", open that board.
    if not window.offer_recovery() and len(sys.argv) > 1:
        window.open_path(sys.argv[1])

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
