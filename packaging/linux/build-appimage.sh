#!/bin/bash
# Wraps the PyInstaller folder dist/FC into FC-<version>-x86_64.AppImage (run from the repo root).
# appimagetool is pinned to one release and its SHA-256 is checked before it runs.
set -euo pipefail
VERSION="${1:?usage: build-appimage.sh <version>}"
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.0/appimagetool-x86_64.AppImage"
TOOL_SHA256="46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"

rm -rf AppDir && mkdir -p AppDir/usr/lib
cp -r dist/FC AppDir/usr/lib/FC
install -m 755 packaging/linux/AppRun AppDir/AppRun
cp packaging/linux/FC.desktop AppDir/FC.desktop
cp fc.png AppDir/FC.png
cp fc.png AppDir/.DirIcon

curl -fsSL -o appimagetool.AppImage "$TOOL_URL"
echo "$TOOL_SHA256  appimagetool.AppImage" | sha256sum -c -
chmod +x appimagetool.AppImage

OUT="dist/FC-${VERSION}-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 ./appimagetool.AppImage --no-appstream AppDir "$OUT"
( cd dist && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "built $OUT"
