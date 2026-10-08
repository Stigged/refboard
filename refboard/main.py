"""Start refboard.

Run with:  refboard [a .refboard file]   (once installed)
     or:   python -m refboard [a .refboard file]   (from this folder)

Also:  refboard --install-menu-entry     add refboard to your app menu (Linux)
       refboard --uninstall-menu-entry   take it out again
"""

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QAction, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMainWindow, QMessageBox, QSystemTrayIcon, QToolTip,
)

from .backup import backup_path, forget, left_behind, release, remove_backup
from .board_file import FILE_EXTENSION, BoardFileError, load_board, read_preview, save_board
from . import __version__
from .canvas import Canvas
from .desktop_entry import APP_ID, install_menu_entry, uninstall_menu_entry
from .help_panel import HelpPanel, welcome_shown
from .platform_support import (
    release_always_on_top, set_always_on_top, set_click_through, shortcut_text,
)
from .recent import add_recent_board, recent_boards, remove_recent_board
from .start_panel import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH, CompactMenu, StartPanel
from .tool_panel import EDGE_MARGIN, FADE_OUT_MS, ToolPanel
from .tray_icon import TrayIcon, app_icon
from .window_frame import WindowFrame
from .window_panel import PANEL_GAP, WindowPanel

FILE_FILTER = f"refboard boards (*{FILE_EXTENSION})"
BACKUP_SECONDS = 30  # after a change, a crash backup is written within this many seconds
# In full overlay mode the panels start fading out this soon (milliseconds).
# Waiting for the mouse to leave doesn't work: with click-through on, the
# window takes no mouse input, so to the desktop the mouse has already left.
PANEL_HIDE_DELAY_MS = 400
# Pinned + click-through: the window fades to at most this opacity, so you
# can see what you're clicking on behind it.
CLICK_THROUGH_OPACITY = 0.5


class MainWindow(QMainWindow):
    """The window around the canvas. Handles files: open, save, and the window title."""

    def __init__(self):
        super().__init__()
        # No title bar or border, like PureRef. WindowFrame (below) gives
        # back what the border did: an outline and resizing from the edges.
        self.setWindowFlag(Qt.FramelessWindowHint)
        # Let the desktop show through wherever we paint see-through colors
        # (background opacity, see Canvas). Has to be set before the window
        # is first shown.
        self.setAttribute(Qt.WA_TranslucentBackground)
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

        # Overlay mode: see toggle_pin and toggle_click_through.
        self.pinned = False  # kept on top of other windows
        self.click_through = False  # clicks go to the window behind us
        self.click_through_armed = False  # see changeEvent
        self.pinned_for_click_through = False  # we pinned only because of click-through
        # The window opacity from before pin + click-through faded it (see
        # update_click_through_opacity), or None.
        self.opacity_before_click_through = None
        # That fade happens in step with the panels: wait, then fade smoothly.
        self.opacity_fade_delay = QTimer(self)
        self.opacity_fade_delay.setSingleShot(True)
        self.opacity_fade_delay.setInterval(PANEL_HIDE_DELAY_MS)
        self.opacity_fade_delay.timeout.connect(self.start_opacity_fade)
        self.opacity_fade = QVariantAnimation(self)
        self.opacity_fade.setDuration(FADE_OUT_MS)
        self.opacity_fade.setEasingCurve(QEasingCurve.InOutQuad)
        self.opacity_fade.valueChanged.connect(self.canvas.set_window_opacity)

        # The tool panel on the left edge and the window panel along the
        # bottom; both hidden while the start panel shows.
        self.tool_panel = ToolPanel(self.canvas)
        self.tool_panel.hide()
        self.window_panel = WindowPanel(self.canvas, self)
        self.window_panel.hide()
        self.window_panel.avoid(self.tool_panel)

        # In full overlay mode (see overlay_mode) the panels get out of the
        # way straight away, so only your images float over the screen.
        self.panel_hide_timer = QTimer(self)
        self.panel_hide_timer.setSingleShot(True)
        self.panel_hide_timer.setInterval(PANEL_HIDE_DELAY_MS)
        self.panel_hide_timer.timeout.connect(self.hide_panels)
        self.canvas.opacity_changed.connect(self.update_panels)

        # The tray icon: the way back from click-through (see tray_icon.py).
        # Some desktops have no tray; then Alt+Tab is the only way back.
        self.tray = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = TrayIcon(self)
            self.tray.show()

        # The recent-boards panel floats over the canvas until you start working.
        # Later, Esc brings it back as the menu (see toggle_menu); in a small
        # window the compact menu takes its place. Both send the same signals.
        self.start_panel = StartPanel(self.canvas)
        self.compact_menu = CompactMenu(self.canvas, self.start_panel)
        self.canvas.changed.connect(self.close_start_panel)
        self.start_panel.new_board_requested.connect(self.new_board)
        self.start_panel.open_requested.connect(self.open)
        self.start_panel.open_path_requested.connect(self.open_recent)
        self.start_panel.save_requested.connect(self.save_from_menu)
        self.start_panel.save_as_requested.connect(self.save_as_from_menu)
        self.start_panel.help_requested.connect(self.show_help)
        # The shortcuts list (F1), which is also the welcome on first start.
        self.help_panel = HelpPanel(self.canvas)
        self.help_panel.closed.connect(self.help_closed)
        self.back_to_start_panel = False  # see show_help
        self.refresh_recent()
        # While the menu is open, a click on the canvas closes it.
        self.canvas.viewport().installEventFilter(self)

        # Created after the canvas and panels, so its outline lies on top of them.
        self.frame = WindowFrame(self)

        self.add_shortcut(QKeySequence.New, self.new_board)  # Ctrl+N
        self.add_shortcut(QKeySequence.Save, self.save)  # Ctrl+S
        self.add_shortcut(QKeySequence.SaveAs, self.save_as)  # Ctrl+Shift+S
        self.add_shortcut(QKeySequence.Open, self.open)  # Ctrl+O
        self.add_shortcut(QKeySequence(Qt.Key_Escape), self.toggle_menu)
        self.add_shortcut(QKeySequence(Qt.Key_F1), self.show_help)
        # There's no title bar with a close button, so: Ctrl+W or Ctrl+Q
        # (Cmd on a Mac). Both close the window, asking about unsaved changes.
        self.add_shortcut(QKeySequence("Ctrl+T"), self.toggle_click_through)  # like PureRef
        self.add_shortcut(QKeySequence("Ctrl+W"), self.close)
        self.add_shortcut(QKeySequence("Ctrl+Q"), self.close)

        self.update_title()

    def close_start_panel(self):
        """Hide the start panel (or the menu) and let the window shrink again
        (handy for a small reference window in a screen corner)."""
        self.start_panel.hide()
        self.compact_menu.hide()
        self.show_panels()
        self.setMinimumSize(self.smallest_size())
        self.canvas.setFocus()  # give the keyboard back to the canvas

    # ---- The menu (Esc) ------------------------------------------------------

    def menu_is_open(self):
        return self.start_panel.isVisible() or self.compact_menu.isVisible()

    def toggle_menu(self):
        """Esc: open the menu, or close it (or the start panel) again.

        (While cropping or typing in a note, the canvas keeps Esc for
        itself, and an open opacity slider closes first; see their code.)
        """
        if self.click_through:
            # refboard still has the keyboard: Esc is the quick way out.
            self.toggle_click_through()
            return
        if self.help_panel.isVisible():
            self.help_panel.close_panel()
            return
        if self.menu_is_open():
            self.close_start_panel()
            return
        self.refresh_recent()
        canvas = self.canvas
        if canvas.width() >= MIN_WINDOW_WIDTH and canvas.height() >= MIN_WINDOW_HEIGHT:
            self.start_panel.set_menu_mode(True)
            self.start_panel.show()
            self.start_panel.raise_()
            # Keep the window big enough for it while it's open.
            self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        else:
            # Too small for the full panel: the short list instead, so the
            # window doesn't have to grow.
            self.compact_menu.open(recent_boards_with_previews())

    def show_help(self, welcome=False):
        """The list of shortcuts (F1), or on first start, the welcome."""
        if self.help_panel.isVisible():
            return
        # Opened from the start panel at startup? Then go back to it after.
        self.back_to_start_panel = self.start_panel.isVisible() and not self.start_panel.menu_mode
        self.start_panel.hide()
        self.compact_menu.hide()
        self.help_panel.open(welcome)

    def show_welcome(self):
        self.show_help(welcome=True)

    def help_closed(self):
        if self.back_to_start_panel:
            self.start_panel.show()
            self.start_panel.raise_()
        else:
            self.canvas.setFocus()

    def save_from_menu(self):
        if self.save():
            self.close_start_panel()

    def save_as_from_menu(self):
        if self.save_as():
            self.close_start_panel()

    def eventFilter(self, watched, event):
        # A click on the canvas while the menu is open closes the menu (and
        # does nothing else, so it doesn't also deselect your images). Not
        # at startup: there the start panel stays until you pick something.
        if event.type() == QEvent.MouseButtonPress and self.help_panel.isVisible():
            self.help_panel.close_panel()
            return True
        if (event.type() == QEvent.MouseButtonPress and self.menu_is_open()
                and (self.compact_menu.isVisible() or self.start_panel.menu_mode)):
            self.close_start_panel()
            return True
        return False

    def smallest_size(self):
        """Once the start panel is closed, the window may get this small:
        just big enough for both panels side by side, with a margin all
        round, so they never overlap and are never cut off."""
        tool, bottom = self.tool_panel, self.window_panel
        width = EDGE_MARGIN + tool.width() + PANEL_GAP + bottom.width() + EDGE_MARGIN
        height = EDGE_MARGIN + max(tool.height(), bottom.height()) + EDGE_MARGIN
        return QSize(width, height)

    def refresh_recent(self):
        """Give the start panel the current list of recent boards, with previews."""
        self.start_panel.set_recent(recent_boards_with_previews())

    def add_shortcut(self, keys, method):
        """Run `method` when `keys` are pressed anywhere in the window."""
        action = QAction(self)
        action.setShortcut(keys)
        action.triggered.connect(method)
        self.addAction(action)

    # ---- Overlay mode: on top, click-through --------------------------------

    def overlay_mode(self):
        """Pinned, click-through and see-through, all at once: refboard is
        just images floating over your other work."""
        see_through = (self.canvas.background_opacity < 1 or self.canvas.window_opacity < 1
                       or self.opacity_before_click_through is not None)  # about to fade
        return self.pinned and self.click_through and see_through

    def update_click_through_opacity(self):
        """Pinned and click-through: fade the window to 50% (unless it's
        already fainter). When either turns off, put the opacity back."""
        canvas = self.canvas
        if self.pinned and self.click_through:
            if self.opacity_before_click_through is None:
                self.opacity_before_click_through = canvas.window_opacity
                if canvas.window_opacity > CLICK_THROUGH_OPACITY:
                    self.opacity_fade_delay.start()  # see start_opacity_fade
        elif self.opacity_before_click_through is not None:
            was_fading = (self.opacity_fade_delay.isActive()
                          or self.opacity_fade.state() == QVariantAnimation.Running)
            self.opacity_fade_delay.stop()
            self.opacity_fade.stop()
            # Only undo our own change: if the opacity was changed in the
            # meantime (say, "Reset opacity" in the tray menu), keep that.
            ours = min(self.opacity_before_click_through, CLICK_THROUGH_OPACITY)
            if was_fading or canvas.window_opacity == ours:
                canvas.set_window_opacity(self.opacity_before_click_through)
            self.opacity_before_click_through = None

    def start_opacity_fade(self):
        """Fade the window smoothly down to CLICK_THROUGH_OPACITY."""
        self.opacity_fade.setStartValue(self.canvas.window_opacity)
        self.opacity_fade.setEndValue(CLICK_THROUGH_OPACITY)
        self.opacity_fade.start()

    def update_panels(self):
        """Something changed that could start or end overlay mode."""
        self.window_panel.update()
        if self.start_panel.isVisible():
            return  # the panels stay hidden until the start panel is closed
        if self.overlay_mode():
            if not self.panel_hide_timer.isActive() and self.tool_panel.isVisible():
                self.panel_hide_timer.start()
        else:
            self.show_panels()

    def show_panels(self):
        self.panel_hide_timer.stop()
        self.tool_panel.fade_in()
        self.window_panel.fade_in()

    def hide_panels(self):
        self.tool_panel.fade_out()
        self.window_panel.fade_out()
        self.window_panel.slider.close_slider()

    def toggle_pin(self):
        """Keep the window in front of all others, or stop."""
        if set_always_on_top(self, not self.pinned):
            self.pinned = not self.pinned
            self.pinned_for_click_through = False  # it's your choice now
        else:
            QToolTip.showText(QCursor.pos(), "This desktop doesn't let refboard stay on top.", self)
        self.update_click_through_opacity()
        self.update_panels()

    def toggle_click_through(self):
        """Let clicks go through refboard to the window behind it, or stop.

        While it's on, refboard can't be clicked, so you can't click a button
        to turn it off again. Instead:
        - Right after switching it on, refboard still has the keyboard
          (Wayland doesn't let an app hand it to the window behind), so
          Esc or Ctrl+T turns it off again.
        - Once you've clicked into another app, switching back to refboard
          (Alt+Tab, the taskbar or the tray icon) turns it off: see changeEvent.
        """
        self.click_through = not self.click_through
        # Armed straight away if refboard isn't the active window (for
        # example, switched on from the tray menu); see changeEvent.
        self.click_through_armed = not self.isActiveWindow()
        set_click_through(self, self.click_through)
        if self.click_through:
            # Without staying on top, the window you click behind refboard
            # would come to the front and hide it. So pin it for now.
            if not self.pinned and set_always_on_top(self, True):
                self.pinned = True
                self.pinned_for_click_through = True
            QToolTip.showText(QCursor.pos(), "Clicks now go through refboard.\n"
                              f"{shortcut_text('Ctrl+T')} or Esc turns this off, or switch back to\n"
                              "refboard later (Alt+Tab, the taskbar or the tray icon).", self)
        elif self.pinned_for_click_through:
            set_always_on_top(self, False)
            self.pinned = False
            self.pinned_for_click_through = False
        self.update_click_through_opacity()
        self.update_panels()

    def changeEvent(self, event):
        # Qt calls this when the window becomes active (in front, with the
        # keyboard) or inactive. Right after click-through is switched on
        # refboard is still active, so first wait until it has been inactive
        # once ("armed"); the next time it becomes active, you switched back
        # to it on purpose, so click-through ends.
        if event.type() == QEvent.ActivationChange and self.click_through:
            if not self.isActiveWindow():
                self.click_through_armed = True
            elif self.click_through_armed:
                self.toggle_click_through()
        super().changeEvent(event)

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
            release_always_on_top()
            if self.tray is not None:
                self.tray.hide()  # otherwise it can linger in the tray
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


def recent_boards_with_previews():
    """The recent boards, as a list of (path, preview picture or None)."""
    return [(path, read_preview(path)) for path in recent_boards()]


def main():
    if "--install-menu-entry" in sys.argv[1:]:
        sys.exit(install_menu_entry())
    if "--uninstall-menu-entry" in sys.argv[1:]:
        sys.exit(uninstall_menu_entry())

    app = QApplication(sys.argv)
    app.setApplicationName("refboard")
    app.setApplicationVersion(__version__)
    # Wayland desktops use this to match the window to refboard's app-menu
    # entry (for the taskbar icon and name). It's the .desktop file's name.
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())  # taskbar and Alt+Tab

    window = MainWindow()
    window.show()
    # Crashed last time? Offer the backup first. Otherwise, if started as
    # "refboard some_board.refboard" (or by double-clicking a board), open it.
    files = [arg for arg in app.arguments()[1:] if not arg.startswith("-")]
    if not window.offer_recovery() and files:
        window.open_path(files[0])
    # The very first time: a welcome with the basics, before anything else.
    if not welcome_shown():
        window.show_welcome()

    sys.exit(app.exec())
