"""Make refboard's icon files from the icon drawn in code (tray_icon.paint_icon).

Run from the project folder after changing the icon:
    .venv/bin/python packaging/make_icons.py

Writes refboard/icons/: refboard.svg (any size) and refboard.png
(256 x 256, for the AppImage and app menus).
"""

import sys
from pathlib import Path

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QGuiApplication, QPainter
from PySide6.QtSvg import QSvgGenerator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from refboard.tray_icon import draw_icon, paint_icon  # noqa: E402

ICONS = Path(__file__).resolve().parent.parent / "refboard" / "icons"


def main():
    app = QGuiApplication(sys.argv)  # Qt needs one before it can draw
    ICONS.mkdir(exist_ok=True)

    svg = QSvgGenerator()
    svg.setFileName(str(ICONS / "refboard.svg"))
    svg.setSize(QSize(256, 256))
    svg.setViewBox(QRect(0, 0, 256, 256))
    svg.setTitle("refboard")
    painter = QPainter(svg)
    paint_icon(painter, 256)
    painter.end()

    draw_icon(256).save(str(ICONS / "refboard.png"))
    print("Icons written to", ICONS)
    del app


if __name__ == "__main__":
    main()
