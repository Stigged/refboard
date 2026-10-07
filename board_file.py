"""Saving and loading boards as a single .refboard file.

A .refboard file is really a zip archive (you can open it with Ark). Inside:
    board.json       where every image is, how big, how turned, plus the view
    preview.jpg      a small picture of the board, for the start panel
    images/0.jpg     the pictures themselves, in their original format
    images/1.png
    ...
"""

import json
import os
import zipfile

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRect
from PySide6.QtGui import QImage

FILE_EXTENSION = ".refboard"
FORMAT_VERSION = 1  # bump this if the layout of board.json ever changes
PREVIEW_NAME = "preview.jpg"


class BoardFileError(Exception):
    """Raised when a file can't be opened as a board (damaged, wrong type, ...)."""


def save_board(path, canvas):
    images = []
    board = {"version": FORMAT_VERSION, "images": images}

    center = canvas.view_center()
    board["view"] = {"zoom": canvas.zoom_level(), "x": center.x(), "y": center.y()}

    # Write to a temporary file first and only swap it in at the end, so a
    # crash halfway through never leaves you with a broken board.
    temp_path = str(path) + ".tmp"
    with zipfile.ZipFile(temp_path, "w") as archive:
        # images() goes bottom-most first, so loading in the same order
        # keeps images stacked on top of each other the same way.
        for number, item in enumerate(canvas.images()):
            data, extension = item.file_data()
            name = f"images/{number}.{extension}"
            archive.writestr(name, data)
            images.append(
                {
                    "file": name,
                    "crop": [item.crop.x(), item.crop.y(), item.crop.width(), item.crop.height()],
                    "x": item.pos().x(),
                    "y": item.pos().y(),
                    "scale": item.scale(),
                    "rotation": item.rotation(),
                }
            )
        archive.writestr("board.json", json.dumps(board, indent=2))

        # Turn the preview picture into JPG bytes and store it too.
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        canvas.render_preview().save(buffer, "JPG", 85)
        archive.writestr(PREVIEW_NAME, bytes(buffer.data()))
    os.replace(temp_path, path)


def load_board(path, canvas):
    try:
        with zipfile.ZipFile(path) as archive:
            board = json.loads(archive.read("board.json"))
            if board.get("version", 0) > FORMAT_VERSION:
                raise BoardFileError("This board was made by a newer version of refboard.")

            canvas.clear_board()
            for entry in board["images"]:
                data = archive.read(entry["file"])
                image = QImage.fromData(data)
                if image.isNull():
                    continue  # skip a damaged picture instead of failing the whole board
                extension = entry["file"].rsplit(".", 1)[-1]
                item = canvas.add_image(image, QPointF(0, 0), data, extension)
                if "crop" in entry:  # boards saved before cropping existed have none
                    item.set_crop(QRect(*entry["crop"]))
                item.setPos(entry["x"], entry["y"])
                item.setScale(entry["scale"])
                item.setRotation(entry["rotation"])

            view = board.get("view")
            if view:
                canvas.set_view(view["zoom"], QPointF(view["x"], view["y"]))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as error:
        raise BoardFileError(f"Couldn't open this board:\n{error}") from error


def read_preview(path):
    """The preview picture inside a board file, or None if it has none (or can't be read)."""
    try:
        with zipfile.ZipFile(path) as archive:
            image = QImage.fromData(archive.read(PREVIEW_NAME))
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return None if image.isNull() else image
