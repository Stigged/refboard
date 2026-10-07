"""Crash backups: a hidden copy of the board, so a crash never loses your work.

While you work, the window writes the board to a backup file every so often
(your real file only changes when you save). When refboard closes normally,
the backup is deleted. So if a backup is still there at the next start,
refboard must have crashed (or been killed), and we offer to restore it.

Backups live in ~/.local/share/refboard/backups/. Each running refboard
uses its own file, named after its process number ("pid"): that's how we
tell a crashed refboard's backup from one that's still running.
"""

import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from board_file import FILE_EXTENSION

PREFIX = "backup-"


def backup_folder():
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def backup_path():
    """This refboard's own backup file."""
    return backup_folder() / f"{PREFIX}{os.getpid()}{FILE_EXTENSION}"


def remove_backup(path=None):
    """Delete a backup (this refboard's own, if no path is given)."""
    (path or backup_path()).unlink(missing_ok=True)


def is_running(pid):
    """Is there a program with this process number right now?"""
    try:
        os.kill(pid, 0)  # signal 0 doesn't do anything; it only checks
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # it exists, it just belongs to someone else
    return True


def left_behind():
    """Backups from refboards that aren't running any more. Newest first."""
    found = []
    for path in backup_folder().glob(f"{PREFIX}*{FILE_EXTENSION}"):
        try:
            pid = int(path.stem.removeprefix(PREFIX))
        except ValueError:
            continue  # not one of ours
        if pid != os.getpid() and not is_running(pid):
            found.append(path)
    return sorted(found, key=lambda path: path.stat().st_mtime, reverse=True)
