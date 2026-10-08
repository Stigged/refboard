"""The few places where Linux, Windows and macOS need different handling.

Everything else in refboard uses plain Qt, which already behaves the same
on all three. Keeping the differences here means the rest of the code
doesn't need "if this is a Mac" checks.
"""

import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence

IS_MACOS = sys.platform == "darwin"

EDGE_NAMES = {
    "left": Qt.LeftEdge,
    "right": Qt.RightEdge,
    "top": Qt.TopEdge,
    "bottom": Qt.BottomEdge,
}


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


def start_window_resize(window, edges):
    """Let the operating system resize `window` with the mouse, from `edges`
    (a set with "left", "right", "top" and/or "bottom"). Call this while a
    mouse button is held.

    Works on Windows, X11 and Wayland. macOS doesn't support it, so there
    this returns False and the caller resizes the window itself (see
    WindowFrame.continue_manual_resize).
    """
    handle = window.windowHandle()
    if handle is None:
        return False
    qt_edges = Qt.Edges()
    for edge in edges:
        qt_edges |= EDGE_NAMES[edge]
    return handle.startSystemResize(qt_edges)


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


# ---- Always on top -------------------------------------------------------------
#
# Windows, macOS and X11: Qt's WindowStaysOnTopHint does it.
#
# Wayland: there's no standard way for an app to ask for this, and Qt's hint
# is ignored (tested on KDE). KDE's window manager, KWin, can run small
# JavaScript scripts sent to it over D-Bus (the message bus programs on the
# Linux desktop use to talk to each other). Ours finds the windows that
# belong to refboard's process and switches on their "Keep Above Others",
# the same setting as in the title-bar menu (tested on KDE Plasma 6).

KWIN_SCRIPT = """
for (const window of workspace.windowList()) {
    if (window.pid === %d) {
        window.keepAbove = %s;
    }
}
"""


def kwin_script_name():
    # One per running refboard, so two of them don't unload each other's script.
    return f"refboard-keep-above-{os.getpid()}"


def kwin_script_path():
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
    return folder / f"{kwin_script_name()}.js"


def kwin_scripting():
    """KWin's D-Bus scripting interface, or None if KWin isn't there."""
    # Imported here: Qt's D-Bus part only matters (and may only exist) on Linux.
    from PySide6.QtDBus import QDBusConnection, QDBusInterface
    scripting = QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting",
                               QDBusConnection.sessionBus())
    return scripting if scripting.isValid() else None


def kwin_keep_above(on):
    """Ask KWin to keep our windows above the rest (or stop). True if it worked."""
    from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
    scripting = kwin_scripting()
    if scripting is None:
        return False
    # KWin reads the script from a file.
    path = kwin_script_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(KWIN_SCRIPT % (os.getpid(), "true" if on else "false"))
    except OSError:
        return False
    # A script name can only be loaded once, so unload the previous one first.
    # (We can't unload right after running it: KWin starts it in the background.)
    scripting.call("unloadScript", kwin_script_name())
    reply = scripting.call("loadScript", str(path), kwin_script_name())
    if reply.type() == QDBusMessage.ErrorMessage or reply.arguments()[0] < 0:
        return False
    script = QDBusInterface("org.kde.KWin", f"/Scripting/Script{reply.arguments()[0]}",
                            "org.kde.kwin.Script", QDBusConnection.sessionBus())
    return script.call("run").type() != QDBusMessage.ErrorMessage


def set_always_on_top(window, on):
    """Keep `window` in front of all other windows (or stop). Returns False
    if this desktop doesn't allow it (Wayland without KDE)."""
    if QGuiApplication.platformName() == "wayland":
        return kwin_keep_above(on)
    handle = window.windowHandle()
    if handle is None:
        return False
    # Set on the native window, not the widget: QWidget.setWindowFlag would
    # destroy and re-create the window, which makes it flicker.
    handle.setFlag(Qt.WindowStaysOnTopHint, on)
    return True


def release_always_on_top():
    """refboard is closing: take our script back out of KWin."""
    if QGuiApplication.platformName() != "wayland":
        return
    scripting = kwin_scripting()
    if scripting is not None:
        scripting.call("unloadScript", kwin_script_name())
    kwin_script_path().unlink(missing_ok=True)


# ---- Click-through -------------------------------------------------------------

def set_click_through(window, on):
    """Let mouse clicks go through `window` to whatever is behind it.

    Qt's WindowTransparentForInput uses each system's own way (on Wayland:
    an empty "input region", tested on KDE). It's set on the native window,
    not the widget: QWidget.setWindowFlag would re-create the window, and on
    Wayland the new one would be placed in the middle of the screen.
    """
    handle = window.windowHandle()
    if handle is not None:
        handle.setFlag(Qt.WindowTransparentForInput, on)
