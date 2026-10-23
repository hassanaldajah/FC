#!/bin/bash
# Wraps the PyInstaller folder dist/FC into FC-<version>-x86_64.AppImage (run from the repo root).
# appimagetool and the AppImage runtime are pinned to one release each and their SHA-256 is
# checked before use (left alone, appimagetool would download the newest runtime unchecked).
# The runtime is the static type-2 one: it needs no libfuse2, which Ubuntu 22.04 and later
# no longer install, and without FUSE at all it can still extract itself and run.
set -euo pipefail
VERSION="${1:?usage: build-appimage.sh <version>}"
TOOL_URL="https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage"
TOOL_SHA256="ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"
RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64"
RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"

rm -rf AppDir && mkdir -p AppDir/usr/lib
cp -r dist/FC AppDir/usr/lib/FC
cp packaging/linux/FC.desktop AppDir/FC.desktop
cp fc.png AppDir/FC.png
cp fc.png AppDir/.DirIcon

# the newest glibc symbol any bundled program or library asks for = the oldest glibc FC runs on
# (objdump fails on the few files that are not ELF, such as scripts: that is fine)
NEED_GLIBC="$( { find AppDir/usr/lib/FC -type f \( -name '*.so*' -o -perm -u+x \) -exec objdump -T {} + 2>/dev/null || true; } \
    | grep -oE 'GLIBC_[0-9]+\.[0-9]+(\.[0-9]+)?' | sed 's/GLIBC_//' | sort -uV | tail -n1 || true)"
[ -n "$NEED_GLIBC" ] || { echo "could not work out the glibc version the bundle needs"; exit 1; }
echo "the bundle needs glibc $NEED_GLIBC or newer"
sed "s/@NEED_GLIBC@/$NEED_GLIBC/" packaging/linux/AppRun > AppDir/AppRun
chmod 755 AppDir/AppRun
echo "$NEED_GLIBC" > dist/needs-glibc.txt

curl -fsSL -o appimagetool.AppImage "$TOOL_URL"
echo "$TOOL_SHA256  appimagetool.AppImage" | sha256sum -c -
chmod +x appimagetool.AppImage
curl -fsSL -o runtime-x86_64 "$RUNTIME_URL"
echo "$RUNTIME_SHA256  runtime-x86_64" | sha256sum -c -

OUT="dist/FC-${VERSION}-x86_64.AppImage"
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 ./appimagetool.AppImage --no-appstream --runtime-file runtime-x86_64 AppDir "$OUT"
( cd dist && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )
echo "built $OUT"
