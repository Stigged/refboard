"""Saving and loading boards as a single .refboard file.

A .refboard file is really a zip archive (you can open it with Ark). Inside:
    board.json       where every image and note is, how big, how turned, plus the view
    preview.jpg      a small picture of the board, for the start panel
    images/0.jpg     the pictures themselves, in their original format
    images/1.png
    ...
"""

import json
import os
import zipfile

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRect
from PySide6.QtGui import QImage, QPixmap

from note_item import NoteItem

FILE_EXTENSION = ".refboard"
# Bump this if the layout of board.json changes. 2 added notes, flipping,
# grayscale and "z" (stacking order).
FORMAT_VERSION = 2
PREVIEW_NAME = "preview.jpg"


class BoardFileError(Exception):
    """Raised when a file can't be opened as a board (damaged, wrong type, ...)."""


def save_board(path, canvas, extra=None, preview=True):
    """Write the board to `path`.

    `extra` is a dict of additional things to store in board.json (crash
    backups use it to remember which file the board belongs to).
    `preview=False` skips the preview picture, to save quicker.
    """
    images, notes = [], []
    board = {"version": FORMAT_VERSION, "images": images, "notes": notes, **(extra or {})}

    center = canvas.view_center()
    board["view"] = {"zoom": canvas.zoom_level(), "x": center.x(), "y": center.y()}

    # Duplicated images share the same file bytes; store those only once.
    # id() is a number that's unique for each object in memory.
    stored = {}  # id(file bytes) -> name inside the archive

    # Write to a temporary file first and only swap it in at the end, so a
    # crash halfway through never leaves you with a broken board.
    temp_path = str(path) + ".tmp"
    with zipfile.ZipFile(temp_path, "w") as archive:
        # board_items() goes bottom-most first; "z" remembers that order.
        for z, item in enumerate(canvas.board_items()):
            placement = {
                "x": item.pos().x(),
                "y": item.pos().y(),
                "scale": item.scale(),
                "rotation": item.rotation(),
                "z": z,
            }
            if isinstance(item, NoteItem):
                notes.append({"text": item.toPlainText(), **placement})
                continue

            data, extension = item.file_data()
            name = stored.get(id(data))
            if name is None:
                name = f"images/{len(stored)}.{extension}"
                archive.writestr(name, data)
                stored[id(data)] = name
            images.append(
                {
                    "file": name,
                    "crop": [item.crop.x(), item.crop.y(), item.crop.width(), item.crop.height()],
                    "flip_h": item.flipped_h,
                    "flip_v": item.flipped_v,
                    "grayscale": item.grayscale,
                    **placement,
                }
            )
        archive.writestr("board.json", json.dumps(board, indent=2))

        if preview:
            # Turn the preview picture into JPG bytes and store it too.
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            canvas.render_preview().save(buffer, "JPG", 85)
            archive.writestr(PREVIEW_NAME, bytes(buffer.data()))
    os.replace(temp_path, path)


def load_board(path, canvas):
    """Replace what's on the canvas with the board in `path`. Returns the
    contents of board.json, for anything else the caller wants from it."""
    try:
        with zipfile.ZipFile(path) as archive:
            board = json.loads(archive.read("board.json"))
            if board.get("version", 0) > FORMAT_VERSION:
                raise BoardFileError("This board was made by a newer version of refboard.")

            canvas.clear_board()
            pictures = {}  # name -> (pixmap, file bytes), so duplicates are only read once
            for entry in board["images"]:
                name = entry["file"]
                if name not in pictures:
                    data = archive.read(name)
                    pictures[name] = (QPixmap.fromImage(QImage.fromData(data)), data)
                pixmap, data = pictures[name]
                if pixmap.isNull():
                    continue  # skip a damaged picture instead of failing the whole board
                extension = name.rsplit(".", 1)[-1]
                item = canvas.add_image(pixmap, QPointF(0, 0), data, extension)
                # Boards from older versions don't have all of these.
                item.set_look(entry.get("flip_h", False), entry.get("flip_v", False),
                              entry.get("grayscale", False))
                if "crop" in entry:
                    item.set_crop(QRect(*entry["crop"]))
                place(item, entry)

            for entry in board.get("notes", []):
                place(canvas.add_note(entry["text"], QPointF(0, 0)), entry)

            view = board.get("view")
            if view:
                canvas.set_view(view["zoom"], QPointF(view["x"], view["y"]))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, TypeError) as error:
        raise BoardFileError(f"Couldn't open this board:\n{error}") from error
    return board


def place(item, entry):
    """Position, size, rotation and stacking height from a board.json entry."""
    item.setPos(entry["x"], entry["y"])
    item.setScale(entry["scale"])
    item.setRotation(entry["rotation"])
    if "z" in entry:  # older boards: the order they were loaded in is the order
        item.setZValue(entry["z"])


def read_preview(path):
    """The preview picture inside a board file, or None if it has none (or can't be read)."""
    try:
        with zipfile.ZipFile(path) as archive:
            image = QImage.fromData(archive.read(PREVIEW_NAME))
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return None if image.isNull() else image
