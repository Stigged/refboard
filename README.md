# refboard

A reference board for artists: drop in your reference images, arrange them
on an endless canvas, and keep them floating over the program you're
working in.

refboard is written in Python with [PySide6](https://doc.qt.io/qtforpython-6/)
(Qt). It's inspired by [PureRef](https://www.pureref.com/), but it's a separate,
independent project with its own code. It isn't affiliated with PureRef or
its makers.

## Features

- **Endless canvas.** Pan, zoom, and fit everything in view.
- **Images from anywhere.** Drag them in from your file manager, or paste
  them (Ctrl+V), for example after "Copy image" in a browser or a screenshot.
- **Arrange.** Move, scale, rotate, crop, flip and turn images black and
  white. Snap edges to each other. Arrange a selection in tidy rows.
- **Text notes** on the board.
- **Undo and redo** for everything.
- **Board files** (`.refboard`). The images are stored inside the file, so a
  board keeps working when the original images move. A start screen shows
  your recent boards.
- **Crash backups.** If refboard closes unexpectedly, it offers to restore
  your board the next time it starts.
- **Overlay mode**, for working over another program (like tracing over a
  3D view in Blender):
  - a frameless window
  - keep on top of other windows
  - see-through background (your images stay solid) and window opacity
  - click-through: clicks go to the window behind refboard
  - the panels fade away while overlay mode is on
- **Tray icon** with the overlay switches. Clicking it also ends click-through.

## Running it

You need Python 3 (it's developed with Python 3.14).

```sh
git clone https://github.com/Stigged/refboard.git
cd refboard
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python main.py
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\python` instead.

You can also open a board directly: `.venv/bin/python main.py my-board.refboard`

## Mouse

| | |
|---|---|
| Pan | Middle-drag, or Space + drag |
| Zoom | Scroll |
| Select | Click, or drag a box on empty canvas (Ctrl adds to the selection) |
| Move images | Drag them (hold Shift to move without snapping) |
| Scale | Drag a corner of a selected image, or Ctrl + scroll |
| Rotate | Drag just outside a corner (Shift snaps to 15°), or Alt + scroll |
| Crop | Ctrl + drag an edge or corner of a selected image, or press C |
| Move the window | Alt + drag |
| Resize the window | Drag its edges |
| Menu | Right-click |

## Keyboard

On a Mac, Ctrl is Cmd and Delete is Backspace.

| | |
|---|---|
| Paste images or text | Ctrl+V |
| Copy image | Ctrl+C |
| Duplicate | Ctrl+D |
| Select all | Ctrl+A |
| Delete | Delete |
| Undo / redo | Ctrl+Z / Ctrl+Shift+Z |
| Crop mode (Enter to finish, Esc to cancel) | C |
| Flip horizontally / vertically | H / V |
| Black and white | G |
| Arrange selection in rows | A |
| New text note | T |
| Fit everything in view | F |
| Bring forward / send backward | ] / [ |
| Bring to front / send to back | Ctrl+] / Ctrl+[ |
| Background opacity / window opacity | O / Shift+O |
| Reset both opacities to 100% | Ctrl+Shift+O |
| New / open / save / save as | Ctrl+N / Ctrl+O / Ctrl+S / Ctrl+Shift+S |
| Close | Ctrl+W or Ctrl+Q |

## Platforms

refboard is developed on Linux (KDE Plasma, Wayland) and uses plain Qt
wherever it can, so it should also run on Windows and macOS. It hasn't
been tested there yet. A few overlay features depend on the desktop:

- **Keep on top** on Wayland only works on KDE Plasma (through a KWin
  script). On X11, Windows and macOS it uses Qt's normal way.
- **Window opacity** is drawn by refboard itself, so it works everywhere,
  including Wayland.

See [research/cross-platform-audit.md](research/cross-platform-audit.md)
for the details.

## License

refboard is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3, as published by the
Free Software Foundation. See [LICENSE](LICENSE).

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.
