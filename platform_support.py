"""The few places where Linux, Windows and macOS need different handling.

Everything else in refboard uses plain Qt, which already behaves the same
on all three. Keeping the differences here means the rest of the code
doesn't need "if this is a Mac" checks.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence

IS_MACOS = sys.platform == "darwin"


def start_window_move(window):
    """Let the operating system move `window` with the mouse, as if you were
    dragging its title bar. Call this while a mouse button is held.

    Qt's startSystemMove works on Windows, macOS, X11 and Wayland, and
    gives the native feel (snapping to screen edges and so on). It returns
    False where the system doesn't support it; then the caller should move
    the window itself (see Canvas.mouseMoveEvent).
    """
    handle = window.windowHandle()
    return handle is not None and handle.startSystemMove()


def shortcut_text(keys):
    """A shortcut written the way this system shows it, for menus and tooltips.

    Qt treats "Ctrl" as the Command key on macOS, so "Ctrl+C" is shown there
    as "⌘C". On Linux and Windows the text stays exactly as written.
    """
    return QKeySequence(keys).toString(QKeySequence.NativeText)


def delete_shortcut_text():
    return shortcut_text("Backspace") if IS_MACOS else shortcut_text("Del")


def is_delete_key(key):
    """Mac keyboards label Backspace as "delete" and have no Delete key
    (only fn+delete), so on macOS Backspace deletes too."""
    return key == Qt.Key_Delete or (IS_MACOS and key == Qt.Key_Backspace)
