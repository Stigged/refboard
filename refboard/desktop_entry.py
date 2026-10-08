"""Adding refboard to the app menu on Linux (and taking it out again).

On Linux desktops (KDE, GNOME, ...) an app shows up in the app menu when
there's a ".desktop" file for it in ~/.local/share/applications. Next to
that we put:

- the icon, in the standard icon folder, so the menu and taskbar can show it;
- a MIME type: a small file that tells the desktop "files ending in
  .refboard are refboard boards". With that, double-clicking a board in
  the file manager opens it in refboard.

    refboard --install-menu-entry
    refboard --uninstall-menu-entry
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# The app's ID: a reverse domain name, the convention on Linux desktops.
# It's also the name of the .desktop file, which Wayland uses to match the
# running window to its menu entry (see main.py).
APP_ID = "io.github.Stigged.refboard"
MIME_TYPE = "application/x-refboard"
ICONS = Path(__file__).parent / "icons"

DESKTOP_FILE = """[Desktop Entry]
Type=Application
Name=refboard
GenericName=Reference board
Comment=Arrange reference images on an endless canvas
Exec={command} %f
Icon={app_id}
Terminal=false
Categories=Graphics;2DGraphics;Viewer;
MimeType={mime_type};
StartupWMClass=refboard
"""

MIME_FILE = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="{mime_type}">
    <comment>refboard board</comment>
    <sub-class-of type="application/zip"/>
    <glob pattern="*.refboard"/>
    <icon name="{app_id}"/>
  </mime-type>
</mime-info>
"""


def data_folder():
    """Where per-user app data lives: usually ~/.local/share."""
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def installed_files():
    data = data_folder()
    return {
        "desktop": data / "applications" / f"{APP_ID}.desktop",
        "svg": data / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
        "png": data / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png",
        "mime": data / "mime" / "packages" / f"{APP_ID}.xml",
    }


def launch_command():
    """The command that starts this same refboard, for the menu entry."""
    if os.environ.get("APPIMAGE"):  # running from an AppImage: that file
        parts = [os.environ["APPIMAGE"]]
    elif getattr(sys, "frozen", False):  # a standalone (PyInstaller) build
        parts = [sys.executable]
    elif Path(sys.argv[0]).name == "refboard":  # the installed "refboard" command
        parts = [str(Path(sys.argv[0]).resolve())]
    else:  # python -m refboard
        parts = [sys.executable, "-m", "refboard"]
    # The .desktop format wants paths with spaces in double quotes.
    return " ".join(f'"{part}"' if " " in part else part for part in parts)


def refresh_desktop_databases():
    """Tell the desktop to re-read the menu entries and MIME types. These
    tools are on almost every Linux desktop; if one is missing, the desktop
    picks the changes up by itself a bit later."""
    data = data_folder()
    for command in (["update-mime-database", str(data / "mime")],
                    ["update-desktop-database", str(data / "applications")]):
        if shutil.which(command[0]):
            subprocess.run(command, check=False, capture_output=True)


def install_menu_entry():
    """Returns an exit code: 0 = done."""
    if not sys.platform.startswith("linux"):
        print("The app-menu entry is for Linux only.")
        return 1
    files = installed_files()
    try:
        for path in files.values():
            path.parent.mkdir(parents=True, exist_ok=True)
        files["desktop"].write_text(DESKTOP_FILE.format(
            command=launch_command(), app_id=APP_ID, mime_type=MIME_TYPE))
        files["mime"].write_text(MIME_FILE.format(app_id=APP_ID, mime_type=MIME_TYPE))
        shutil.copyfile(ICONS / "refboard.svg", files["svg"])
        shutil.copyfile(ICONS / "refboard.png", files["png"])
    except OSError as error:
        print(f"Couldn't add refboard to the app menu: {error}")
        return 1
    refresh_desktop_databases()
    print(f"refboard is in your app menu now (it starts: {launch_command()}).")
    print(".refboard files open in refboard when you double-click them.")
    return 0


def uninstall_menu_entry():
    for path in installed_files().values():
        path.unlink(missing_ok=True)
    refresh_desktop_databases()
    print("refboard's app-menu entry is removed.")
    return 0
