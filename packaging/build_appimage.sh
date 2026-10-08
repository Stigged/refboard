#!/bin/sh
# Build refboard as an AppImage: one file that runs on most Linux systems,
# without installing Python or Qt.
#
# Run from the project folder:   sh packaging/build_appimage.sh
# Result:                        build/refboard-x86_64.AppImage
#
# Steps:
# 1. PyInstaller collects refboard, Python and the parts of Qt it uses into
#    one folder (build/dist/refboard), with a "refboard" program in it.
# 2. That folder goes into an "AppDir" with an icon, a .desktop file and a
#    small AppRun script, the layout an AppImage expects.
# 3. appimagetool packs the AppDir into the single .AppImage file.
set -eu

PYTHON=.venv/bin/python
BUILD=build
APP_ID=io.github.Stigged.refboard
ARCH=x86_64

"$PYTHON" -m pip install --quiet pyinstaller

echo "1/3 Collecting refboard with PyInstaller..."
rm -rf "$BUILD/dist" "$BUILD/work" "$BUILD/AppDir"
"$PYTHON" -m PyInstaller --noconfirm --clean --log-level WARN \
    --name refboard --windowed \
    --add-data "$PWD/refboard/icons:refboard/icons" \
    --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
    packaging/launcher.py

echo "2/3 Making the AppDir..."
APPDIR="$BUILD/AppDir"
mkdir -p "$APPDIR/usr/lib"
cp -r "$BUILD/dist/refboard" "$APPDIR/usr/lib/refboard"
cp refboard/icons/refboard.png "$APPDIR/$APP_ID.png"
cp refboard/icons/refboard.png "$APPDIR/.DirIcon"
cat > "$APPDIR/$APP_ID.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=refboard
GenericName=Reference board
Comment=Arrange reference images on an endless canvas
Exec=refboard %f
Icon=$APP_ID
Terminal=false
Categories=Graphics;2DGraphics;Viewer;
MimeType=application/x-refboard;
StartupWMClass=refboard
DESKTOP
# AppRun is what runs when you start the AppImage.
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/refboard/refboard" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

echo "3/3 Packing the AppImage..."
TOOL="$BUILD/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
    chmod +x "$TOOL"
fi
# --appimage-extract-and-run: works even where FUSE isn't set up.
ARCH=$ARCH "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$BUILD/refboard-$ARCH.AppImage" >/dev/null 2>&1 \
    || ARCH=$ARCH "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$BUILD/refboard-$ARCH.AppImage"

echo "Done: $BUILD/refboard-$ARCH.AppImage ($(du -h "$BUILD/refboard-$ARCH.AppImage" | cut -f1))"
