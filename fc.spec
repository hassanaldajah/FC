# PyInstaller recipe for FC:  pyinstaller --clean --noconfirm fc.spec
# Both systems get the folder dist/FC (FC.exe or FC plus its _internal libraries), never one
# self-unpacking file: that had to unpack ~160 MB to a temporary folder at every start, which
# took many seconds. Windows: packaging/windows/FC.iss turns the folder into an installer.
# Linux: packaging/linux/build-appimage.sh wraps it into an AppImage. No UPX (packed exes
# look suspicious to antivirus), no console window.
import re
import sys

from PyInstaller.utils.hooks import collect_data_files

WIN = sys.platform == "win32"
datas = [("hex.qml", "."), ("fc.ico", "."), ("fc.png", "."), ("fc-mark.png", "."), ("icons", "icons")]
datas += collect_data_files("imageio_ffmpeg", subdir="binaries")   # the bundled ffmpeg

a = Analysis(
    ["fc.py"],
    datas=datas,
    hiddenimports=["PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtNetwork", "selftest"]
    + (["pynput.keyboard._win32", "pynput.mouse._win32", "comtypes.stream"] if WIN
       else ["pynput.keyboard._xorg", "pynput.mouse._xorg", "PyQt6.QtDBus"]),
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
# Parts of Qt and OpenCV that FC never loads: leaving them out makes the app
# much smaller and quicker to start. Re-test the app after changing this list.
UNUSED = ("quick3d", "designer", "qt6pdf", "multimedia", "websockets", "webchannel", "texttospeech",
          "sensors", "remoteobjects", "positioning", "qttest", "qt6test", "translations")
if WIN:   # on Linux the OpenCV module links libavcodec & co. directly, so those must stay
    UNUSED += ("avcodec", "avformat", "avutil", "swscale", "swresample", "opencv_videoio_ffmpeg")

# Linux: libraries every desktop already has, in versions that must match its graphics drivers,
# GTK and fonts. Bundling the build machine's older copies breaks newer systems (e.g. Mesa's
# drivers need a newer libstdc++ than Ubuntu 22.04's), so the system's own are used. Libraries a
# fresh install may lack (libxcb-cursor, libxkbcommon-x11, the other xcb helpers) stay bundled.
SYSTEM_LIBS = re.compile(r"^(libstdc\+\+|libgcc_s|libglib-2\.0|libgobject-2\.0|libgio-2\.0|libgmodule-2\.0|"
                         r"libgthread-2\.0|libfontconfig|libfreetype|libharfbuzz|libX11|libX11-xcb|"
                         r"libdbus-1|libz|libexpat|libuuid|libselinux|libmount|libblkid|libpcre2-8|"
                         r"libsystemd|libudev|libcap|libgcrypt|libgpg-error)\.so(\.|$)")


def keep(entry):
    path = entry[0].replace("\\", "/").lower()
    if any(word in path for word in UNUSED):
        return False
    return WIN or not SYSTEM_LIBS.match(entry[0].replace("\\", "/").rsplit("/", 1)[-1])


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FC",
    icon="fc.ico" if WIN else None,
    version="version_info.txt" if WIN else None,
    console=False,
    upx=False,
    strip=False,
    debug=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="FC", upx=False, strip=False)
