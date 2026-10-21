# PyInstaller recipe for HK File.exe:  pyinstaller --clean --noconfirm hkfile.spec
# One file, no UPX (packed exes look suspicious to antivirus), no console window.
from PyInstaller.utils.hooks import collect_data_files

datas = [("hex.qml", "."), ("hkfile.ico", "."), ("icons", "icons")]
datas += collect_data_files("imageio_ffmpeg", subdir="binaries")   # the bundled ffmpeg.exe

a = Analysis(
    ["hkfile.py"],
    datas=datas,
    hiddenimports=["PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtNetwork", "pynput.keyboard._win32",
                   "pynput.mouse._win32", "comtypes.stream"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
)
# Parts of Qt and OpenCV that HK File never loads: leaving them out makes the exe
# much smaller and quicker to start. Re-test the app after changing this list.
UNUSED = ("quick3d", "designer", "qt6pdf", "multimedia", "avcodec", "avformat", "avutil",
          "swscale", "swresample", "websockets", "webchannel", "texttospeech", "sensors",
          "remoteobjects", "positioning", "qttest", "qt6test", "translations",
          "opencv_videoio_ffmpeg")


def keep(entry):
    path = entry[0].replace("\\", "/").lower()
    return not any(word in path for word in UNUSED)


a.binaries = [e for e in a.binaries if keep(e)]
a.datas = [e for e in a.datas if keep(e)]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="HK File",
    icon="hkfile.ico",
    version="version_info.txt",
    console=False,
    upx=False,
    strip=False,
    debug=False,
)
