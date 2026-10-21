"""FC: a frosted-glass octagon that converts, compresses, merges, splits
and protects files. Runs on Windows and Linux.

Open it and the octagon appears on screen (with its own taskbar button).
Drop files on it, pick them from its "Choose files" side, or (on Windows) select
files in File Explorer and press Ctrl+Alt+C or hold Shift and scroll: the octagon
turns into the tools for those files. Results are saved where you choose;
nothing is overwritten and nothing leaves the computer.
"""
from __future__ import annotations

import ctypes
import hashlib
import logging
import math
import os
import shutil
import subprocess
import sys
import threading
import time
import warnings
from ctypes import wintypes
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from PyQt6.QtCore import (QObject, QPoint, QPointF, Qt, QThread, QTimer, QUrl, pyqtProperty,
                          pyqtSignal, pyqtSlot)
from PyQt6.QtGui import QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QImage, QPolygonF, QRegion
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtQuick import QQuickImageProvider, QQuickView
from PyQt6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QFileDialog,
                             QInputDialog, QLabel, QLineEdit, QVBoxLayout)

import explorer
import file_tools
import history
import scanner

IS_WIN = sys.platform == "win32"
APP_ID = "HassanAldajah.FC"
INSTANCE_KEY = "FC-single-instance"
VERSION = "1.1.0"                     # keep in step with version_info.txt and the release tag
HERE = Path(__file__).resolve().parent
if IS_WIN:
    LOG_DIR = Path(os.environ.get("LOCALAPPDATA", str(HERE))) / "FC"
    EXPLORER = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "explorer.exe")   # full path, never a look-alike
else:
    LOG_DIR = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local" / "state"))) / "FC"

SIDES = 8                            # panes in the octagon; must match sideCount in hex.qml
HOME = [("Choose files", "home:pick"), ("Scan", ">Scan"), ("Recent", ">Recent"),
        ("PDF", "home:pdf"), ("Images", "home:images"), ("Office", "home:office"),
        ("Media", "home:media"), ("Other files", "home:other")]
PICK_FILTERS = {
    "home:pick": "All files (*)",
    "home:other": "Any file (*)",
    "home:pdf": "PDF files (*.pdf)",
    "home:images": "Images (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.tif *.tiff *.ico)",
    "home:office": "Office files (*.docx *.doc *.rtf *.odt *.xlsx *.xls *.csv *.pptx *.ppt)",
    "home:media": "Audio and video (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.opus *.mp4 *.mkv *.mov *.avi *.webm *.wmv)",
}

# clear, consistent colours (Apple system colours, dark-mode values)
COLORS = {"pdf": "#ff453a", "image": "#30d158", "office": "#0a84ff", "media": "#bf5af2",
          "pick": "#5e5ce6", "other": "#ac8e68", "scan": "#64d2ff", "recent": "#ff9f0a", "neutral": "#636366"}
HOME_COLOR = {">Scan": "scan", "virus:check": "scan", "home:pick": "pick", ">Recent": "recent", "home:pdf": "pdf", "home:images": "image",
              "home:office": "office", "home:media": "media", "home:other": "other", "home:scan": "scan", "recent:open": "recent",
              "recent:compare": "recent", "recent:versions": "recent"}


# ------------------------------------------------------------------ triggers
class Triggers(QObject):
    """Ctrl+Alt+C, registered with Windows on its own thread (works in every
    keyboard layout), and Shift + mouse wheel while File Explorer is in front.
    On Linux: Ctrl+Alt+C through X11 (Wayland does not allow global hotkeys)."""
    fired = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._last = 0.0
        self.hotkey_ok = None
        if not IS_WIN:
            self._start_linux()
            return
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

        from pynput import mouse
        get_key = ctypes.windll.user32.GetAsyncKeyState

        def on_scroll(_x, _y, _dx, _dy):
            if get_key(0x10) & 0x8000 and explorer.foreground_is_explorer():   # Shift held
                self.fire()

        self._mouse = mouse.Listener(on_scroll=on_scroll)
        self._mouse.daemon = True
        self._mouse.start()

    def _start_linux(self):
        try:
            from pynput import keyboard
            self._keys = keyboard.GlobalHotKeys({"<ctrl>+<alt>+c": self.fire})
            self._keys.daemon = True
            self._keys.start()
            self.hotkey_ok = True
        except Exception:  # noqa: BLE001 - no X11 (Wayland, headless): the octagon still works
            logging.warning("Ctrl+Alt+C is not available on this desktop session")
            self.hotkey_ok = False

    def _hotkey_loop(self):
        user32 = ctypes.windll.user32
        user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                       wintypes.UINT, wintypes.UINT]
        MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY = 0x1, 0x2, 0x4000, 0x0312
        self.hotkey_ok = bool(user32.RegisterHotKey(None, 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT,
                                                    ord("C")))
        if not self.hotkey_ok:
            logging.warning("Ctrl+Alt+C is already used by another program")
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                self.fire()                 # a queued signal: safe across threads

    def fire(self):
        now = time.monotonic()
        if now - self._last > 0.6:          # one wheel spin = one menu
            self._last = now
            self.fired.emit()


# ------------------------------------------------------------------ worker
class Worker(QThread):
    """Runs jobs off the UI thread. A job is (name, callable returning paths)."""
    done = pyqtSignal(list, list)            # outputs, errors

    def __init__(self, jobs):
        super().__init__()
        self.jobs = jobs

    def run(self):
        if IS_WIN:
            import comtypes
            comtypes.CoInitialize()
        outputs, errors = [], []
        try:
            for name, job in self.jobs:
                try:
                    outputs.extend(job())
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{name}: {exc}")
        finally:
            if IS_WIN:
                comtypes.CoUninitialize()
        self.done.emit(outputs, errors)


class HashJob(QThread):
    """SHA-256 of a file, off the UI thread (files can be gigabytes)."""
    done = pyqtSignal(str, str)              # file name, hex digest ("" if unreadable)

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def run(self):
        digest = hashlib.sha256()
        try:
            with open(self.path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError:
            self.done.emit(self.path.name, "")
            return
        self.done.emit(self.path.name, digest.hexdigest())


# ------------------------------------------------------------------ the hexagon
ICON_DIR = HERE / "icons"
ICONS = {   # Lucide icons in ./icons, white, 1.5 px stroke
    "home:pick": "folder-open", ">Recent": "history", "home:pdf": "file-text",
    "home:images": "image", "home:office": "briefcase", "home:media": "clapperboard",
    "home:other": "file-archive", "home:scan": "scan-line", ">Scan": "scan-line", "virus:check": "shield",
    "recent:open": "folder-open", "recent:compare": "git-compare", "recent:versions": "history",
    ">Convert": "repeat", ">Pages": "layers", ">Security": "shield", ">Edit": "pencil",
    ">ImageEdit": "pencil", "merge": "combine", "split": "scissors", "extract": "file-output",
    "remove": "file-minus", "rot_r": "rotate-cw", "rot_l": "rotate-cw", "rot_180": "rotate-cw",
    "reverse": "arrow-down-up", "repair": "wrench", "protect": "lock", "unlock": "lock-open",
    "strip": "eraser", "watermark": "stamp", "numbers": "hash", "to_jpg": "image",
    "to_png": "image", "to_word": "file-type", "to_txt": "file-type", "to_pptx": "file-type",
    "images": "images", "img_pdf": "file-text", "zip": "file-archive", "zip_lock": "file-lock",
    "img_resize": "scaling", "img_rotate": "rotate-cw",
}


def icon_for(key: str) -> str:
    name = ICONS.get(key)
    if name is None:
        for part, icon in (("watermark", "stamp"), ("compress", "minimize-2"), ("merge", "combine"),
                           ("split", "scissors"), ("protect", "lock"), ("fmt:", "repeat")):
            if part in key:
                name = icon
                break
    return QUrl.fromLocalFile(str(ICON_DIR / f"{name or 'file-type'}.svg")).toString()


def reduced_motion() -> bool:
    """Windows 'Show animations in Windows' switched off = keep motion minimal."""
    if not IS_WIN:
        return False
    try:
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)  # SPI_GETCLIENTAREAANIMATION
        return not on.value
    except Exception:  # noqa: BLE001
        return False


def app_icon() -> QIcon:
    icon = HERE / ("fc.ico" if IS_WIN else "fc.png")
    return QIcon(str(icon)) if icon.exists() else QIcon()


class ShotProvider(QQuickImageProvider):
    """Hands the blurred-glass layer a snapshot of the desktop behind us."""
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)
        self.image = QImage()

    def requestImage(self, _id, _size):
        return self.image, self.image.size()


class Backend(QObject):
    """State shared with hex.qml."""
    changed = pyqtSignal()
    openRequested = pyqtSignal()
    closeRequested = pyqtSignal(str)
    optionsReplaced = pyqtSignal()
    chosen = pyqtSignal(str)
    dropped = pyqtSignal(list)
    moveRequested = pyqtSignal()
    glassRequested = pyqtSignal()
    closeFinished = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._options: list[dict] = []
        self._keys: list[str] = []
        self._title = ""
        self._flash = ""
        self._drop = False
        self._win = (0, 0)
        self._shot = ""
        self._calm = reduced_motion()
        self._first = True                   # the opening animation plays once
        self.kind = "neutral"                 # tint of the menus for the current files
        self.home = True
        self.stack: list[tuple] = []
        self.resolve = lambda group: []
        self.flash_timer = QTimer(self)
        self.flash_timer.setSingleShot(True)
        self.flash_timer.timeout.connect(lambda: self.set_flash(""))

    # ---- properties read by QML
    @pyqtProperty("QVariantList", notify=changed)
    def options(self): return self._options

    @pyqtProperty(str, notify=changed)
    def title(self): return self._title

    @pyqtProperty(str, notify=changed)
    def flash(self): return self._flash

    @pyqtProperty(bool, notify=changed)
    def canGoBack(self): return bool(self.stack) or not self.home

    @pyqtProperty(bool, notify=changed)
    def atHome(self): return self.home and not self.stack

    @pyqtProperty(str, constant=True)
    def logoUrl(self): return QUrl.fromLocalFile(str(HERE / "fc-mark.png")).toString()

    @pyqtProperty(bool, notify=changed)
    def dropActive(self): return self._drop

    @pyqtProperty(float, notify=changed)
    def winX(self): return float(self._win[0])

    @pyqtProperty(float, notify=changed)
    def winY(self): return float(self._win[1])

    @pyqtProperty(str, notify=changed)
    def shotUrl(self): return self._shot

    @pyqtProperty(bool, constant=True)
    def reducedMotion(self): return self._calm

    @pyqtProperty(bool, notify=changed)
    def firstOpen(self): return self._first

    @pyqtSlot()
    def opened(self):
        # read by QML only when opening, so no change signal: emitting one here would make
        # every binding re-evaluate in the middle of the opening animation
        self._first = False

    @pyqtProperty(str, constant=True)
    def iconDir(self): return QUrl.fromLocalFile(str(ICON_DIR)).toString() + "/"

    # ---- setters used from Python
    def set_menu(self, options, title: str):
        self._keys = [k for _, k in options]
        self._options = [{"label": lbl, "icon": icon_for(k), "group": k.startswith(">"),
                          "color": COLORS[HOME_COLOR.get(k, "neutral") if self.home else self.kind]}
                         for lbl, k in options]
        self._title = title
        self.changed.emit()
        self.optionsReplaced.emit()

    def set_flash(self, text: str, seconds: float = 0):
        self._flash = text
        self.changed.emit()
        if text and seconds:
            self.flash_timer.start(int(seconds * 1000))

    def set_window(self, x: int, y: int):
        self._win = (x, y)
        self.changed.emit()

    def set_shot(self, url: str):
        self._shot = url
        self.changed.emit()

    # ---- slots called from QML
    @pyqtSlot(int)
    def pick(self, k: int):
        if not 0 <= k < len(self._keys):
            return
        key = self._keys[k]
        if key.startswith(">"):                       # a group: its tools
            self.stack.append(([(o["label"], kk) for o, kk in zip(self._options, self._keys)], self._title))
            self.set_menu(self.resolve(key[1:]), self._options[k]["label"])
            return
        self.chosen.emit(key)

    @pyqtSlot()
    def back(self):
        if self.stack:
            options, title = self.stack.pop()
            self.set_menu(options, title)
        elif not self.home:
            self.chosen.emit("home:back")

    @pyqtSlot()
    def escape(self):
        if self.stack or not self.home:
            self.back()
        else:
            self.closeRequested.emit("min")

    @pyqtSlot(bool)
    def setDropActive(self, on: bool):
        self._drop = on
        self.changed.emit()

    @pyqtSlot("QVariantList")
    def dropUrls(self, urls):
        files = [Path(QUrl(u).toLocalFile()) for u in urls]
        files = [f for f in files if f.is_file()]
        if files:
            self.dropped.emit(files)

    @pyqtSlot()
    def minimize(self): self.closeRequested.emit("min")

    @pyqtSlot()
    def help(self):
        self.set_flash("Drop files, or Ctrl+Alt+C in Explorer", 6)

    @pyqtSlot()
    def quit(self): self.closeRequested.emit("quit")

    @pyqtSlot()
    def startMove(self): self.moveRequested.emit()

    @pyqtSlot()
    def refreshGlass(self): self.glassRequested.emit()

    @pyqtSlot(str)
    def closeDone(self, kind: str): self.closeFinished.emit(kind)


class HexView(QObject):
    """The window: a frameless, transparent Qt Quick view showing hex.qml."""
    chosen = pyqtSignal(str)
    dropped = pyqtSignal(list)
    W, H, CY, R = 400, 424, 226, 186     # must match hex.qml

    def __init__(self):
        super().__init__()
        self.backend = Backend()
        self.backend.chosen.connect(self.chosen)
        self.backend.dropped.connect(self.dropped)
        self.backend.moveRequested.connect(lambda: self.view.startSystemMove())
        self.backend.closeFinished.connect(self._close_finished)
        self.provider = ShotProvider()
        self.shot_version = 0
        self.shot_origin = QPoint(0, 0)
        self.was_minimized = False

        self.view = QQuickView()
        self.view.setTitle("FC")
        self.view.setIcon(app_icon())
        self.view.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.view.setColor(QColor(0, 0, 0, 0))
        self.view.engine().addImageProvider("shot", self.provider)
        self.view.rootContext().setContextProperty("backend", self.backend)
        self.view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.view.setSource(QUrl.fromLocalFile(str(HERE / "hex.qml")))
        for err in self.view.errors():
            logging.error("QML: %s", err.toString())
        self.view.resize(self.W, self.H)
        self.view.xChanged.connect(self._moved)
        self.view.yChanged.connect(self._moved)
        self.settle = QTimer(singleShot=True, interval=180)      # a move has ended: fresh glass
        self.settle.timeout.connect(self._refresh_glass)
        self.backend.glassRequested.connect(self._refresh_glass)
        self.view.xChanged.connect(self.settle.start)
        self.view.yChanged.connect(self.settle.start)
        self.view.windowStateChanged.connect(self._state_changed)
        self._set_mask()

    # ---- window shape: clicks outside the hexagon and buttons go through
    def _set_mask(self):
        """Only the hexagon (with room for its shadow) and the buttons take clicks."""
        start = -90 - 180 / SIDES                   # flat top, like hex.qml
        pts = [QPointF(self.W / 2 + (self.R + 23) * math.cos(math.radians(start + 360 / SIDES * k)),
                       self.CY + (self.R + 23) * math.sin(math.radians(start + 360 / SIDES * k)))
               for k in range(SIDES)]
        buttons = QRegion(self.W // 2 + 68, self.CY - self.R - 34, 72, 36)
        self.view.setMask(QRegion(QPolygonF(pts).toPolygon()).united(buttons))

    def _allow_taskbar_minimize(self):
        """Frameless windows ignore taskbar clicks; give it a minimize box."""
        if not IS_WIN:
            return
        GWL_STYLE, WS_MINIMIZEBOX, WS_SYSMENU = -16, 0x00020000, 0x00080000
        user32 = ctypes.windll.user32
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        hwnd = int(self.view.winId())
        style = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style | WS_MINIMIZEBOX | WS_SYSMENU)

    def _moved(self):
        self.backend.set_window(self.view.x() - self.shot_origin.x(),
                                self.view.y() - self.shot_origin.y())

    def _state_changed(self, state):
        minimized = bool(state & Qt.WindowState.WindowMinimized)
        if self.was_minimized and not minimized:      # back from the taskbar:
            self.view.requestActivate()               # reuse the glass we have, so the
            self.backend.openRequested.emit()          # animation starts on the very next frame
        self.was_minimized = minimized

    # ---- the glass: snapshot the desktop while we are invisible, then pop in
    def _refresh_and_open(self, pos: QPoint | None):
        self.view.setOpacity(0.0)
        if pos is not None:                     # the hexagon's centre lands on pos
            screen = (QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()).availableGeometry()
            x = min(max(pos.x() - self.W // 2, screen.left()), screen.right() - self.W)
            y = min(max(pos.y() - self.CY, screen.top()), screen.bottom() - self.H)
            self.view.setPosition(x, y)
        QTimer.singleShot(30, self._grab_and_show)

    def _grab_desktop(self):
        """Snapshot what is behind the window for the glass. While grabbing, the window is
        excluded from screen capture (Windows 10 2004+), so it never photographs itself."""
        centre = self.view.geometry().center()
        screen = QGuiApplication.screenAt(centre) or QGuiApplication.primaryScreen()
        excluded = False
        if IS_WIN:
            hwnd = wintypes.HWND(int(self.view.winId()))
            WDA_NONE, WDA_EXCLUDEFROMCAPTURE = 0x0, 0x11
            excluded = bool(ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE))
        try:
            img = screen.grabWindow(0).toImage()
        finally:
            if excluded:
                ctypes.windll.user32.SetWindowDisplayAffinity(hwnd, WDA_NONE)
        self.settle.stop()                   # this snapshot is fresh: no second grab after it
        self.provider.image = img
        self.shot_origin = screen.geometry().topLeft()
        self.shot_version += 1
        self.backend.set_shot(f"image://shot/{self.shot_version}")
        self._moved()
        return img, screen

    def _refresh_glass(self):
        """Re-take the snapshot after a move, or when the mouse comes back."""
        if self.view.isVisible() and not self.is_minimized() and self.view.opacity() > 0:
            self._grab_desktop()

    def _grab_and_show(self):
        img, screen = self._grab_desktop()
        if img.isNull() or all(img.pixelColor(img.width() * i // 5, img.height() * j // 5).value() == 0
                               for i in range(1, 5) for j in range(1, 5)):
            logging.warning("desktop snapshot is empty (%sx%s, dpr %s): the glass will look flat",
                            img.width(), img.height(), screen.devicePixelRatio())
        if os.environ.get("FC_DEBUG_SHOT"):           # troubleshooting: keep what the glass sees
            img.save(str(LOG_DIR / "last-snapshot.png"))
        # let the GPU upload and blur the new snapshot while we are still
        # invisible; the animation starts only once that work is done
        self._frames_left = 2
        self.view.frameSwapped.connect(self._after_warmup)
        self.view.update()

    def _after_warmup(self):
        self._frames_left -= 1
        if self._frames_left > 0:
            self.view.update()
            return
        self.view.frameSwapped.disconnect(self._after_warmup)
        self.view.setOpacity(1.0)
        self.view.raise_()
        self.view.requestActivate()
        self.backend.openRequested.emit()

    # ---- what the app calls
    def present(self, pos: QPoint | None, options, title: str, home: bool):
        self.backend.stack = []
        self.backend.home = home
        self.backend.set_menu(options, title)
        if not self.view.isVisible():
            self.view.show()
            self._allow_taskbar_minimize()
            self._refresh_and_open(pos or self.view.position() + QPoint(self.W // 2, self.CY))
        elif self.is_minimized() or pos is not None:
            if self.is_minimized():
                self.view.showNormal()
            self._refresh_and_open(pos)
        else:
            self.view.requestActivate()

    def set_resolver(self, fn):
        self.backend.resolve = fn

    def flash(self, text: str, seconds: float = 3.0):
        self.backend.set_flash(text, seconds)

    def minimize(self):
        self.backend.closeRequested.emit("min")

    def quit(self):
        self.backend.closeRequested.emit("quit")

    def _close_finished(self, kind: str):
        if kind == "quit":
            QGuiApplication.instance().quit()
        else:
            self.view.showMinimized()

    def is_minimized(self) -> bool:
        return bool(self.view.windowState() & Qt.WindowState.WindowMinimized)

    def is_visible(self) -> bool:
        return self.view.isVisible()

    def is_active(self) -> bool:
        return self.view.isActive()

    def alert(self):
        self.view.alert(3000)


# ------------------------------------------------------------------ opening things
def show_in_folder(path: Path):
    """Open the folder holding path, with the file selected where the file manager can."""
    if IS_WIN:
        subprocess.Popen([EXPLORER, "/select,", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


def open_folder(folder: Path):
    subprocess.Popen([EXPLORER, str(folder)] if IS_WIN else ["xdg-open", str(folder)])


def open_file(path: Path):
    if IS_WIN:
        os.startfile(path)                       # opens in the photo viewer
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ------------------------------------------------------------------ app
class App(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.hexagon = HexView()
        self.hexagon.chosen.connect(self.on_choice)
        self.hexagon.dropped.connect(self.open_for_files)
        self.files: list[Path] = []
        self.results: list[Path] = []
        self.last_sources: list[Path] = []      # what the last tool started from
        self.last_outputs: list[Path] = []      # and what it made
        self.workers: list[Worker] = []
        self.triggers = Triggers()
        self.triggers.fired.connect(self.open_from_explorer)
        self.go_home(centre=True)
        self.hexagon.flash("Ready")

    def go_home(self, centre: bool = False):
        pos = None
        if centre:
            screen = QApplication.primaryScreen().availableGeometry()
            pos = screen.center()
        self.hexagon.set_resolver(self.home_group)
        self.hexagon.present(pos, HOME, "FC", home=True)

    def home_group(self, group: str):
        if group == "Scan":
            return [("Virus check", "virus:check"), ("Paper scan", "home:scan")]
        if group == "Recent":
            return [("Open folder", "recent:open"), ("Compare", "recent:compare"),
                    ("Versions", "recent:versions")]
        return []

    def bring_front(self):
        self.go_home(centre=self.hexagon.is_minimized())

    def open_from_explorer(self):
        files = explorer.selected_files()
        if not files:
            self.hexagon.present(None if self.hexagon.is_visible() and not self.hexagon.is_minimized()
                                 else QCursor.pos(), HOME, "FC", home=True)
            if IS_WIN:                  # Linux file managers cannot tell us the selection
                self.hexagon.flash("Select files first")
            return
        self.open_for_files(files, at_cursor=True)

    def scan(self):
        """Scan a page, save it where the user wants, then show the image tools for it."""
        target = QFileDialog.getExistingDirectory(None, "FC: where to save the scan?",
                                                  str(Path.home() / "Desktop"))
        if not target:
            self.hexagon.flash("Cancelled", 2)
            return
        try:
            page = scanner.scan_to(Path(target))
        except scanner.NoScanner:
            self.hexagon.flash("No scanner found. Is it on?")
            return
        except Exception:  # noqa: BLE001 - driver problems: tell the user, keep running
            logging.exception("scan failed")
            self.hexagon.flash("The scanner didn't answer")
            return
        if page is None:
            self.hexagon.flash("Cancelled", 2)
            return
        self._tell_explorer(page)
        self.open_for_files([page])                  # next: PDF, compress, protect...
        self.hexagon.flash("Scanned ✓")

    def virus_check(self):
        """Hash one file here, then open its VirusTotal page in the browser.
        Only the hash leaves the computer, never the file."""
        if self.hexagon.backend.home:
            name, _ = QFileDialog.getOpenFileName(None, "FC: choose a file to check", "", "All files (*)")
            target = Path(name) if name else None
        else:
            target = self.files[0] if self.files else None
        if target is None or not target.is_file():
            self.hexagon.flash("Cancelled", 2)
            return
        self.hexagon.flash("Checking…", 600)
        job = HashJob(target)
        job.done.connect(lambda n, h, j=job: self._virus_hash_ready(n, h, j))
        self.workers.append(job)
        job.start()

    def _virus_hash_ready(self, name: str, digest: str, job):
        self.workers.remove(job)
        if not digest:
            self.hexagon.flash("Could not read that file", 4)
            return
        QGuiApplication.clipboard().setText(digest)
        QDesktopServices.openUrl(QUrl(f"https://www.virustotal.com/gui/file/{digest}"))
        self.hexagon.flash("Opened VirusTotal. Hash copied", 6)

    def open_for_files(self, files, at_cursor: bool = False):
        options = file_tools.top_menu(files)[:SIDES]
        if not options:
            self.hexagon.flash("Can't use these together")
            return
        if len(options) < SIDES:
            options.append(("Virus check", "virus:check"))
        self.files = files
        kinds = {file_tools.kind_of(f) for f in files}
        kind = kinds.pop() if len(kinds) == 1 else None
        self.hexagon.backend.kind = {"pdf": "pdf", "image": "image", "word": "office", "sheet": "office",
                                     "slides": "office", "audio": "media", "video": "media"}.get(kind, "neutral")
        self.hexagon.set_resolver(lambda group, files=files: file_tools.group_menu(group, files)[:SIDES])
        label = files[0].suffix.upper().lstrip(".") if len(files) == 1 else f"{len(files)} files"
        self.hexagon.present(QCursor.pos() if at_cursor else None, options, label, home=False)

    def on_choice(self, key: str):
        if key in PICK_FILTERS:
            names, _ = QFileDialog.getOpenFileNames(None, "Choose files for FC", "",
                                                    PICK_FILTERS[key])
            if names:
                self.open_for_files([Path(n) for n in names])
        elif key == "recent:open":
            if self.results and Path(self.results[-1]).exists():
                show_in_folder(self.results[-1])
            else:
                self.hexagon.flash("No results yet")
        elif key == "recent:compare":
            before = next((p for p in self.last_sources if p.exists()), None)
            after = next((p for p in self.last_outputs if Path(p).exists()), None)
            if before and after:
                open_file(history.compare(before, Path(after)))
            else:
                self.hexagon.flash("Run a tool first")
        elif key == "recent:versions":
            src = next((p for p in self.last_sources if history.versions_dir(p).exists()), None)
            if src:
                open_folder(history.versions_dir(src))
            else:
                self.hexagon.flash("No versions yet")
        elif key == "home:scan":
            self.scan()
        elif key == "virus:check":
            self.virus_check()
        elif key == "home:back":
            self.go_home()
        else:
            self.run_tool(key)

    def _ask(self, needs: str) -> str | None:
        """Password, watermark text, page numbers or minutes; None when cancelled."""
        if needs == "password":
            text, ok = QInputDialog.getText(None, "FC", "Password:", QLineEdit.EchoMode.Password)
        elif needs == "text":
            text, ok = QInputDialog.getText(None, "FC", "Watermark text:",
                                            QLineEdit.EchoMode.Normal, "CONFIDENTIAL")
        elif needs == "minutes":
            text, ok = QInputDialog.getText(None, "FC", "Length of each part in minutes:",
                                            QLineEdit.EchoMode.Normal, "5")
        else:
            text, ok = QInputDialog.getText(None, "FC", "Pages (e.g. 1-3, 5, 8-):")
        return text if ok and text.strip() else None

    def run_tool(self, key: str):
        files = list(self.files)
        if key.startswith("fmt:"):
            jobs = [(f.name, lambda f=f: file_tools.run(key, [f])) for f in files]
            title = key[4:].upper()
        else:
            label, _tool, needs, scope = file_tools.TOOLS[key]
            arg = ""
            if needs:
                arg = self._ask(needs)
                if arg is None:
                    return
            if scope == "all":
                jobs = [(label, lambda: file_tools.run(key, files, arg))]
            else:
                jobs = [(f.name, lambda f=f: file_tools.run(key, [f], arg)) for f in files]
            title = label
        # last step before running: where should the results go?
        start = str(files[0].parent) if files else str(Path.home() / "Desktop")
        target = QFileDialog.getExistingDirectory(None, f"FC: where to save ({title})?", start)
        if not target:
            self.hexagon.flash("Cancelled", 2)
            return
        target = Path(target)
        worker = Worker(jobs)
        worker.sources = files
        worker.done.connect(lambda outs, errs, w=worker: self.finished(w, outs, errs, title, target))
        self.workers.append(worker)
        self.go_home()
        self.hexagon.flash("Working…", 600)
        worker.start()

    @staticmethod
    def _move_to(path: Path, folder: Path) -> Path:
        """Move a result into the chosen folder without replacing anything there."""
        path = Path(path)
        if path.parent.resolve() == folder.resolve():
            return path
        dest = folder / path.name
        n = 2
        while dest.exists():
            dest = folder / (f"{path.stem} ({n}){path.suffix}" if path.is_file() else f"{path.name} ({n})")
            n += 1
        shutil.move(str(path), str(dest))
        return dest

    @staticmethod
    def _tell_explorer(path: Path):
        """Tell Windows a file was created, so Explorer draws its real icon at once."""
        if not IS_WIN:
            return
        try:
            SHCNE_CREATE, SHCNE_MKDIR, SHCNE_UPDATEDIR, SHCNF_PATHW = 0x2, 0x8, 0x1000, 0x5
            shell32 = ctypes.windll.shell32
            shell32.SHChangeNotify(SHCNE_MKDIR if path.is_dir() else SHCNE_CREATE, SHCNF_PATHW,
                                   ctypes.c_wchar_p(str(path)), None)
            shell32.SHChangeNotify(SHCNE_UPDATEDIR, SHCNF_PATHW, ctypes.c_wchar_p(str(path.parent)), None)
        except Exception:  # noqa: BLE001
            pass

    def finished(self, worker, outputs, errors, title, target: Path):
        self.workers.remove(worker)
        moved = []
        for out in outputs:
            try:
                moved.append(self._move_to(out, target))
            except OSError as exc:
                errors.append(f"{Path(out).name}: could not move it ({exc})")
                moved.append(Path(out))
        outputs = moved
        for out in outputs:
            self._tell_explorer(Path(out))
        self.results.extend(outputs)
        if outputs:
            self.last_sources, self.last_outputs = list(worker.sources), list(outputs)
            try:
                history.save_versions(worker.sources, outputs, title)
            except OSError as exc:
                logging.warning("Could not save versions: %s", exc)
        for err in errors:
            logging.warning("%s failed: %s", title, err)
        if errors and not outputs:
            self.hexagon.flash("Failed: " + errors[0].split(": ", 1)[-1][:40], 6)
        elif errors:
            self.hexagon.flash(f"Done ✓ ({len(errors)} failed)", 5)
        else:
            self.hexagon.flash("Done ✓", 5)
        if self.hexagon.is_minimized() or not self.hexagon.is_active():
            self.hexagon.alert()                      # blink the taskbar button


# ------------------------------------------------------------------ first-run setup
def install_dir() -> Path:
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Programs" / "FC"
    return Path.home() / ".local" / "share" / "FC"


def downloaded_binary() -> Path | None:
    """The exe (or AppImage) the user started, if it is a release build that is not installed yet."""
    if not getattr(sys, "frozen", False):
        return None                                   # running from source
    path = Path(os.environ.get("APPIMAGE") or (sys.executable if IS_WIN else "")) if (
        IS_WIN or os.environ.get("APPIMAGE")) else None
    if path is None or not path.is_file():
        return None
    return None if path.resolve().parent == install_dir().resolve() else path.resolve()


def _desktop_folder() -> Path:
    if IS_WIN:
        import comtypes.client
        return Path(comtypes.client.CreateObject("WScript.Shell").SpecialFolders("Desktop"))
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out:
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def _make_shortcut(link: Path, target: Path):
    """Windows .lnk through WScript.Shell; paths travel in environment variables, never in the script text."""
    script = ("$l=(New-Object -ComObject WScript.Shell).CreateShortcut($env:FC_LNK);"
              "$l.TargetPath=$env:FC_TARGET;$l.WorkingDirectory=Split-Path $env:FC_TARGET;"
              "$l.IconLocation=$env:FC_TARGET+',0';"
              "$l.Description='FC: convert, compress and edit files';$l.Save()")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                   env={**os.environ, "FC_LNK": str(link), "FC_TARGET": str(target)})


def install_app(source: Path, desktop: bool, menu: bool) -> Path:
    """Copy the download to a permanent place and add the shortcuts the user ticked."""
    folder = install_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / ("FC.exe" if IS_WIN else "FC.AppImage")
    shutil.copy2(source, dest)
    if IS_WIN:
        import comtypes.client
        shell = comtypes.client.CreateObject("WScript.Shell")
        places = ([Path(shell.SpecialFolders("Desktop"))] if desktop else []) + (
            [Path(shell.SpecialFolders("Programs"))] if menu else [])
        for place in places:
            _make_shortcut(place / "FC.lnk", dest)
    else:
        dest.chmod(0o755)
        icon_dir = Path.home() / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps"
        icon_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / "fc.png", icon_dir / "FC.png")
        entry = ("[Desktop Entry]\nType=Application\nName=FC\n"
                 "Comment=Convert, compress, merge, split and protect files\n"
                 f'Exec="{dest}"\nIcon=FC\nCategories=Utility;\nTerminal=false\nStartupWMClass=FC\n')
        if menu:
            apps = Path.home() / ".local" / "share" / "applications"
            apps.mkdir(parents=True, exist_ok=True)
            (apps / "FC.desktop").write_text(entry, encoding="utf-8")
        if desktop:
            link = _desktop_folder() / "FC.desktop"
            link.parent.mkdir(parents=True, exist_ok=True)
            link.write_text(entry, encoding="utf-8")
            link.chmod(0o755)
            try:                                       # GNOME: let the icon launch without a warning
                subprocess.run(["gio", "set", str(link), "metadata::trusted", "true"], timeout=5,
                               capture_output=True)
            except (OSError, subprocess.SubprocessError):
                pass
    return dest


def offer_install() -> bool:
    """First run of a downloaded copy: offer to install it with shortcuts, like an installer.
    Returns True when it installed and started the installed copy, so this process should exit."""
    source = downloaded_binary()
    skip = LOG_DIR / "setup-declined"
    if source is None or skip.exists() or os.environ.get("FC_NO_SETUP"):
        return False
    dialog = QDialog()
    dialog.setWindowTitle("FC setup")
    dialog.setWindowIcon(app_icon())
    layout = QVBoxLayout(dialog)
    label = QLabel("Install FC on this computer?\n\nIt is copied out of your Downloads folder so it "
                   "stays when you clean that up. Nothing is sent anywhere.")
    label.setWordWrap(True)
    layout.addWidget(label)
    desktop = QCheckBox("Create a shortcut on the Desktop")
    menu = QCheckBox("Add FC to the Start menu" if IS_WIN else "Add FC to the applications menu")
    never = QCheckBox("Don't ask again, just run")
    desktop.setChecked(True)
    menu.setChecked(True)
    for box in (desktop, menu, never):
        layout.addWidget(box)
    buttons = QDialogButtonBox()
    install_btn = buttons.addButton("Install", QDialogButtonBox.ButtonRole.AcceptRole)
    buttons.addButton("Just run", QDialogButtonBox.ButtonRole.RejectRole)
    install_btn.setDefault(True)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        if never.isChecked():
            skip.write_text("declined", encoding="utf-8")
        return False
    try:
        dest = install_app(source, desktop.isChecked(), menu.isChecked())
    except Exception:  # noqa: BLE001 - never block the app because setup failed
        logging.exception("install failed")
        return False
    logging.info("installed to %s", dest)
    subprocess.Popen([str(dest)], cwd=str(dest.parent), close_fds=True)
    return True


def single_instance(on_show) -> QLocalServer | None:
    """If FC already runs, bring its hexagon forward and return None."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_KEY)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return None
    QLocalServer.removeServer(INSTANCE_KEY)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)   # only this user
    server.listen(INSTANCE_KEY)

    def on_connect():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(on_show)
    server.newConnection.connect(on_connect)
    return server


def selftest() -> int:
    """Release check (fc --selftest): every bundled library loads. Run by the build workflow."""
    import importlib
    for name in ("PyQt6.QtQuick", "PyQt6.QtQml", "PyQt6.QtNetwork", "PIL.Image", "pymupdf",
                 "pyzipper", "pptx", "pdf2docx", "imageio_ffmpeg"):
        importlib.import_module(name)
    import imageio_ffmpeg
    ok = (HERE / "hex.qml").exists() and Path(imageio_ffmpeg.get_ffmpeg_exe()).exists()
    print("FC", VERSION, "selftest", "ok" if ok else "FAILED")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    os.chdir(HERE)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / "fc.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    sys.excepthook = lambda t, v, tb: logging.critical("crash", exc_info=(t, v, tb))
    if IS_WIN:
        try:  # our own taskbar button and icon instead of Python's
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:  # noqa: BLE001
            pass
    qapp = QApplication(sys.argv)
    qapp.setDesktopFileName("FC")          # Linux: matches FC.desktop, so the taskbar shows our icon
    if offer_install():
        return
    qapp.setWindowIcon(app_icon())
    holder: list = []
    server = single_instance(lambda: holder and holder[0].bring_front())
    if server is None:
        return
    app = App(qapp)
    holder.append(app)
    logging.info("FC started")
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
