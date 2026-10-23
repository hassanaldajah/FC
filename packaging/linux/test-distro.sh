#!/bin/sh
# Runs FC's self-test inside a fresh container of one Linux distribution (the release workflow
# does this for each distribution in its list). It installs only what any desktop install
# already has (OpenGL, fonts, GLib, D-Bus, the X11 client library) plus a virtual screen, so
# anything else FC needs must come inside the AppImage.
#   test-distro.sh <AppImage> <glibc FC needs> [must-run]
# On a system with that glibc or newer the self-test must pass. On an older one FC must refuse
# with a clear message, unless must-run is given: then an older system is a failure as well.
set -eu
APP="$1"
NEED="$2"
MUST_RUN="${3:-}"

. /etc/os-release
HAVE="$(getconf GNU_LIBC_VERSION | cut -d' ' -f2)"
echo "== $PRETTY_NAME, glibc $HAVE (FC needs $NEED)"
cp "$APP" /tmp/FC.AppImage
chmod +x /tmp/FC.AppImage
export APPIMAGE_EXTRACT_AND_RUN=1        # containers have no FUSE; the AppImage unpacks itself instead
export HOME=/tmp/home XDG_RUNTIME_DIR=/tmp/runtime
mkdir -p "$HOME" "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

if [ "$(printf '%s\n%s\n' "$NEED" "$HAVE" | sort -V | head -n1)" != "$NEED" ]; then
    [ -z "$MUST_RUN" ] || { echo "FC must run on $PRETTY_NAME, but it needs glibc $NEED"; exit 1; }
    if out="$(/tmp/FC.AppImage --selftest 2>&1)"; then
        echo "FC started on a system it should refuse:"; echo "$out"; exit 1
    fi
    echo "$out" | tail -n 3
    echo "$out" | grep -q "FC needs Linux with glibc" || { echo "no clear message"; exit 1; }
    echo "== refused with a clear message, as it should"
    exit 0
fi

# a supported system: add what any desktop has, then run the whole self-test
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends xvfb xauth libgl1 libegl1 libgl1-mesa-dri libglib2.0-0 \
        libfontconfig1 libfreetype6 fonts-dejavu-core libx11-6 libx11-xcb1 libdbus-1-3 >/dev/null
elif command -v dnf >/dev/null 2>&1; then
    dnf install -y -q mesa-libGL mesa-libEGL mesa-dri-drivers glib2 fontconfig freetype dejavu-sans-fonts \
        libX11 libX11-xcb dbus-libs findutils >/dev/null
    dnf install -y -q xorg-x11-server-Xvfb >/dev/null 2>&1 || echo "no Xvfb package here"
elif command -v zypper >/dev/null 2>&1; then
    zypper --non-interactive --quiet install --no-recommends xorg-x11-server-Xvfb Mesa-libGL1 Mesa-libEGL1 Mesa-dri \
        libglib-2_0-0 fontconfig libfreetype6 dejavu-fonts libX11-6 libX11-xcb1 libdbus-1-3 >/dev/null
elif command -v pacman >/dev/null 2>&1; then
    pacman -Sy --noconfirm --needed --quiet xorg-server-xvfb mesa glib2 fontconfig freetype2 ttf-dejavu \
        libx11 dbus >/dev/null
else
    echo "unknown package manager"; exit 1
fi

if command -v Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1280x800x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
    export DISPLAY=:99
    for _ in $(seq 1 30); do [ -S /tmp/.X11-unix/X99 ] && break; sleep 1; done
    [ -S /tmp/.X11-unix/X99 ] || { echo "Xvfb did not start:"; cat /tmp/xvfb.log; exit 1; }
else
    echo "== no Xvfb on this distribution: the window part runs on Qt's offscreen screen"
    export QT_QPA_PLATFORM=offscreen
fi
/tmp/FC.AppImage --selftest
