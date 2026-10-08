"""Remembers which boards you opened or saved most recently.

The list is stored with QSettings, Qt's way of saving small preferences.
On Linux it ends up in ~/.config/refboard/refboard.conf.
"""

from pathlib import Path

from PySide6.QtCore import QSettings

MAX_RECENT = 4  # the start panel shows four
SETTINGS_KEY = "recent_boards"


def _settings():
    return QSettings("refboard", "refboard")


def recent_boards():
    """Paths of recent boards, newest first. Files that no longer exist are skipped."""
    paths = _settings().value(SETTINGS_KEY, [], type=list)
    return [path for path in paths if Path(path).is_file()][:MAX_RECENT]


def add_recent_board(path):
    """Put `path` at the top of the list (moving it there if it was already in it)."""
    path = str(Path(path).resolve())  # full path, so the same file is never listed twice
    paths = [p for p in recent_boards() if p != path]
    _settings().setValue(SETTINGS_KEY, [path] + paths[: MAX_RECENT - 1])


def remove_recent_board(path):
    path = str(Path(path).resolve())
    _settings().setValue(SETTINGS_KEY, [p for p in recent_boards() if p != path])
