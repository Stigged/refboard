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

## Installing

### Linux: AppImage (easiest)

Download `refboard-x86_64.AppImage` from the
[Releases](https://github.com/Stigged/refboard/releases) page. It's a
single file with everything included. Make it executable and run it:

```sh
chmod +x refboard-x86_64.AppImage
./refboard-x86_64.AppImage
```

To add it to your app menu (and open `.refboard` files with a double-click):

```sh
./refboard-x86_64.AppImage --install-menu-entry
```

### Windows

Download `refboard-windows-x64.zip` from the
[Releases](https://github.com/Stigged/refboard/releases) page, extract it
(right-click > Extract All), open the `refboard` folder and double-click
`refboard.exe`.

The first time, Windows may say "Windows protected your PC", because
refboard isn't code-signed (yet). Click **More info**, then **Run anyway**.

Windows support is new and hasn't had much testing yet; if something
doesn't work, please [open an issue](https://github.com/Stigged/refboard/issues).

### Any system with Python: pipx

With [pipx](https://pipx.pypa.io/) (and Python 3.10 or newer):

```sh
pipx install git+https://github.com/Stigged/refboard.git
refboard
```

On Linux, `refboard --install-menu-entry` adds it to your app menu.

### From the source code

```sh
git clone https://github.com/Stigged/refboard.git
cd refboard
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/refboard
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\refboard` instead.

You can also open a board directly: `refboard my-board.refboard`

To build the AppImage yourself: `sh packaging/build_appimage.sh`
(the result lands in `build/`).

To take the app-menu entry out again: `refboard --uninstall-menu-entry`

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
| Click-through on / off (Esc also turns it off) | Ctrl+T |
| Menu: save, save as, new, open, recent boards | Esc |
| All shortcuts | F1 |
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

## License

refboard is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License, version 3, as published by the
Free Software Foundation. See [LICENSE](LICENSE).

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
FITNESS FOR A PARTICULAR PURPOSE.
