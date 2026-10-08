"""Crash backups: a hidden copy of the board, so a crash never loses your work.

While you work, the window writes the board to a backup file every so often
(your real file only changes when you save). When refboard closes normally,
the backup is deleted. So if a backup is still there at the next start,
refboard must have crashed (or been killed), and we offer to restore it.

Backups live in refboard's data folder, under "backups":
    Linux    ~/.local/share/refboard/backups/
    Windows  C:\\Users\\<you>\\AppData\\Roaming\\refboard\\backups\\
    macOS    ~/Library/Application Support/refboard/backups/

Each running refboard uses its own backup file, plus a lock file next to it
that it holds while running (Qt's QLockFile). If we can take over another
backup's lock, the refboard that held it isn't running any more: that's a
backup left behind by a crash. QLockFile checks this the right way on every
operating system.
"""

import os
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths

from .board_file import FILE_EXTENSION

PREFIX = "backup-"
LOCK_EXTENSION = ".lock"

_own_lock = None  # our QLockFile, taken the first time we write a backup


def backup_folder():
    folder = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)) / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def lock_file(backup):
    """The lock file that belongs to a backup file."""
    lock = QLockFile(str(backup.with_suffix(LOCK_EXTENSION)))
    # Never treat a lock as abandoned just because it's old: refboard can
    # run for days. Only "its program isn't running" counts.
    lock.setStaleLockTime(0)
    return lock


def backup_path():
    """This refboard's own backup file. The first call also takes its lock."""
    global _own_lock
    path = backup_folder() / f"{PREFIX}{os.getpid()}{FILE_EXTENSION}"
    if _own_lock is None:
        _own_lock = lock_file(path)
        _own_lock.tryLock(0)
    return path


def remove_backup(path=None):
    """Delete a backup (this refboard's own, if no path is given)."""
    (path or backup_path()).unlink(missing_ok=True)


def release():
    """Closing normally: delete our backup and let go of our lock."""
    global _own_lock
    if _own_lock is not None:
        remove_backup()
        _own_lock.unlock()  # also deletes the lock file
        _own_lock = None


def left_behind():
    """Backups from refboards that aren't running any more. Newest first.

    For each one we return (backup path, its lock, which we now hold).
    Call forget() when done with it.
    """
    try:
        candidates = list(backup_folder().glob(f"{PREFIX}*{FILE_EXTENSION}"))
    except OSError:
        return []  # can't even look in the folder: nothing we could restore anyway
    found = []
    for path in candidates:
        if _own_lock is not None and path == backup_path():
            continue
        lock = lock_file(path)
        if lock.tryLock(0):  # we got it, so its owner is gone
            found.append((path, lock))
    found.sort(key=lambda entry: entry[0].stat().st_mtime, reverse=True)
    return found


def forget(path, lock):
    """Delete a left-behind backup and its lock."""
    remove_backup(path)
    lock.unlock()
