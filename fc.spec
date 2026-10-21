# PyInstaller recipe for FC:  pyinstaller --clean --noconfirm fc.spec
# Windows: one FC.exe, no UPX (packed exes look suspicious to antivirus), no console window.
# Linux: the dist/FC folder, which the release workflow wraps into an AppImage.
import sys

from PyInstaller.utils.hooks import collect_data_files

WIN = sys.platform == "win32"
datas = [("hex.qml", "."), ("fc.ico", "."), ("fc.png", "."), ("fc-mark.png", "."), ("icons", "icons")]
datas += collect_data_files("imageio_ffmpeg", subdir="binaries")   # the bundled ffmpeg

a = Analysis(
    ["fc.py"],
    datas=datas,
    hiddenimports=["PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtNetwork"]
    + (["pynput.keyboard._win32", "pynput.mouse._win32", "comtypes.stream"] if WIN
       else ["pynput.keyboard._xorg", "pynput.mouse._xorg"]),
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
# Parts of Qt and OpenCV that FC never loads: leaving them out makes the exe
# much smaller and quicker to start. Re-test the app after changing this list.
UNUSED = ("quick3d", "designer", "qt6pdf", "multimedia", "websockets", "webchannel", "texttospeech",
          "sensors", "remoteobjects", "positioning", "qttest", "qt6test", "translations")
if WIN:   # on Linux the OpenCV module links libavcodec & co. directly, so those must stay
    UNUSED += ("avcodec", "avformat", "avutil", "swscale", "swresample", "opencv_videoio_ffmpeg")


def keep(entry):
    path = entry[0].replace("\\", "/").lower()
    return not any(word in path for word in UNUSED)


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]
pyz = PYZ(a.pure)
if WIN:
    exe = EXE(
        pyz, a.scripts, a.binaries, a.datas,
        name="FC",
        icon="fc.ico",
        version="version_info.txt",
        console=False,
        upx=False,
        strip=False,
        debug=False,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FC",
              console=False, upx=False, strip=False, debug=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="FC", upx=False, strip=False)
