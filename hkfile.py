"""HK File: select files in File Explorer, press Ctrl+Alt+C (or hold Shift
and scroll), and pick the new format from a hexagon around the mouse.

Runs in the background with a tray icon. Converted files are saved next to
the originals; nothing is overwritten and nothing leaves the computer.
"""
from __future__ import annotations

import math
import os
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from PyQt6.QtCore import (QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF,
                          Qt, QThread, QTimer, pyqtProperty, pyqtSignal)
from PyQt6.QtGui import (QAction, QBrush, QColor, QCursor, QFont, QIcon, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)
from PyQt6.QtWidgets import QApplication, QInputDialog, QLineEdit, QMenu, QSystemTrayIcon, QWidget

import converters
import explorer
import file_tools

ACCENT = QColor(255, 51, 68)
NAVY = QColor(13, 20, 40, 235)
TEXT = QColor(244, 246, 251)
MUTED = QColor(164, 177, 205)
SIZE = 360          # overlay window
R_OUT = 150         # hexagon radius
R_IN = 52           # centre hole
POP_SHIFT = 12      # how far a side lifts out under the mouse (px)
POP_SCALE = 0.09    # and how much bigger it gets


# ------------------------------------------------------------------ hotkeys
class Triggers(QObject):
    """Ctrl+Alt+C, or Shift + mouse wheel, while File Explorer is in front."""
    fired = pyqtSignal()

    def __init__(self):
        super().__init__()
        from pynput import keyboard, mouse

        self._shift = False
        self._last = 0.0

        def on_press(key):
            if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                self._shift = True

        def on_release(key):
            if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
                self._shift = False

        def on_scroll(_x, _y, _dx, _dy):
            if self._shift and explorer.foreground_is_explorer():
                self._fire()

        self._hotkey = keyboard.GlobalHotKeys({"<ctrl>+<alt>+c": self._fire})
        self._keys = keyboard.Listener(on_press=on_press, on_release=on_release)
        self._mouse = mouse.Listener(on_scroll=on_scroll)
        for listener in (self._hotkey, self._keys, self._mouse):
            listener.daemon = True
            listener.start()

    def _fire(self):
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
            comtypes.CoUninitialize()
        self.done.emit(outputs, errors)


# ------------------------------------------------------------------ hexagon
def enable_blur(widget: QWidget) -> bool:
    """Frosted-glass blur of whatever is behind the window (Windows 10/11)."""
    import ctypes
    from ctypes import wintypes

    class AccentPolicy(ctypes.Structure):
        _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

    class CompositionData(ctypes.Structure):
        _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                    ("SizeOfData", ctypes.c_size_t)]

    try:
        accent = AccentPolicy(3, 0, 0, 0)                 # 3 = blur behind
        data = CompositionData(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p),
                               ctypes.sizeof(accent))     # 19 = accent policy
        fn = ctypes.windll.user32.SetWindowCompositionAttribute
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(CompositionData)]
        return bool(fn(int(widget.winId()), ctypes.byref(data)))
    except Exception:  # noqa: BLE001 - no blur: the glass is just a bit more opaque
        return False


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


class HexMenu(QWidget):
    """A hexagon of frosted glass. Six sides, one choice each; the middle goes
    back or closes. Every change (open, hover, switching groups) is animated."""
    chosen = pyqtSignal(str)

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFixedSize(SIZE, SIZE)
        self.options: list[tuple[str, str]] = []
        self.label = ""
        self.stack: list[tuple[list, str]] = []   # menus to go back to
        self.resolve = lambda group: []              # set by the app
        self.hover = -1
        self.glow = [0.0] * 6        # animated highlight of each side, 0..1
        self.centre_glow = 0.0
        self.t_open = 0.0            # 0 -> 1 when the menu appears
        self.t_swap = 1.0            # 0 -> 1 when a group opens or closes
        self.closing = False
        self.blurred = False
        self._last = time.monotonic()
        self.clock = QTimer(self)
        self.clock.setInterval(8)                  # ~120 fps, smooth on fast screens
        self.clock.timeout.connect(self._tick)

    # ---- animation loop: everything eases towards its target each frame
    def _tick(self):
        now = time.monotonic()
        dt = min(0.05, now - self._last)
        self._last = now
        k = 1 - math.exp(-dt * 18)                 # frame-rate independent easing
        for i in range(6):
            self.glow[i] = lerp(self.glow[i], 1.0 if i == self.hover else 0.0, k)
        self.centre_glow = lerp(self.centre_glow, 1.0 if self.hover == -2 else 0.0, k)
        if self.closing:
            self.t_open = max(0.0, self.t_open - dt * 7)
            if self.t_open <= 0.001:
                self.clock.stop()
                self.closing = False
                super().hide()
                return
        else:
            self.t_open = min(1.0, self.t_open + dt * 5.5)
        self.t_swap = min(1.0, self.t_swap + dt * 6)
        self._update_mask()
        self.update()

    def _ease(self, t: float) -> float:            # ease-out with a soft overshoot
        c1, c3 = 1.2, 2.2
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2 if t < 1 else 1.0

    def _scale(self) -> float:
        return 0.82 + 0.18 * self._ease(self.t_open)

    def _update_mask(self):
        from PyQt6.QtGui import QRegion, QTransform
        c = SIZE / 2
        sc = self._scale()
        zoom = QTransform().translate(c, c).scale(sc, sc).translate(-c, -c)
        region = QRegion(zoom.map(QPolygonF([self._corner(k, R_OUT + 2) for k in range(6)])).toPolygon())
        for k in range(min(6, len(self.options))):
            if self.glow[k] > 0.01:
                region = region.united(QRegion(zoom.map(self._pop(k, self.glow[k], 3)).toPolygon()))
        self.setMask(region)

    # ---- open / close
    def open_at(self, pos, options, label: str):
        self.stack = []
        self.options, self.label, self.hover = options, label, -1
        self.glow = [0.0] * 6
        self.t_open, self.t_swap, self.closing = 0.0, 1.0, False
        self.move(pos.x() - SIZE // 2, pos.y() - SIZE // 2)
        self._update_mask()
        self.show()
        if not self.blurred:
            self.blurred = enable_blur(self)
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._last = time.monotonic()
        self.clock.start()

    def hide(self):                                 # fade out instead of vanishing
        if self.isVisible() and not self.closing:
            self.closing = True
            self._last = time.monotonic()
            self.clock.start()

    def pick(self, k: int):
        label, key = self.options[k]
        if key.startswith(">"):                     # a group: show its tools
            self.stack.append((self.options, self.label))
            self.options = self.resolve(key[1:])
            self.label, self.hover = label, -1
            self.t_swap = 0.0
            return
        self.hide()
        self.chosen.emit(key)

    def back(self):
        if self.stack:
            self.options, self.label = self.stack.pop()
            self.hover = -1
            self.t_swap = 0.0
        else:
            self.hide()

    # ---- geometry: six wedges of a hexagon, one per option
    def _corner(self, k: int, radius: float) -> QPointF:
        a = math.radians(60 * k - 90)
        c = SIZE / 2
        return QPointF(c + radius * math.cos(a), c + radius * math.sin(a))

    def _wedge(self, k: int, r_out: float, r_in: float) -> QPolygonF:
        return QPolygonF([self._corner(k, r_in), self._corner(k, r_out),
                          self._corner(k + 1, r_out), self._corner(k + 1, r_in)])

    def _pop_transform(self, k: int, g: float):
        """Lift side k out of the hexagon: move it outwards and make it bigger."""
        from PyQt6.QtGui import QTransform
        c = SIZE / 2
        mid = math.radians(60 * k - 60)
        cx = c + (R_OUT + R_IN) / 2 * math.cos(mid)
        cy = c + (R_OUT + R_IN) / 2 * math.sin(mid)
        dx, dy = POP_SHIFT * g * math.cos(mid), POP_SHIFT * g * math.sin(mid)
        sc = 1 + POP_SCALE * g
        return QTransform().translate(cx + dx, cy + dy).scale(sc, sc).translate(-cx, -cy)

    def _pop(self, k: int, g: float, grow: float = 0.0) -> QPolygonF:
        return self._pop_transform(k, g).map(self._wedge(k, R_OUT + grow, R_IN - grow))

    def _index_at(self, x: float, y: float) -> int:
        c = SIZE / 2
        dx, dy = x - c, y - c
        d = math.hypot(dx, dy)
        if d < R_IN:
            return -2                               # the centre
        if d > R_OUT + 6:
            return -1
        ang = (math.degrees(math.atan2(dy, dx)) + 90) % 360
        k = int(ang // 60)
        return k if k < len(self.options) else -1

    # ---- drawing
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        c = SIZE / 2
        fade = min(1.0, self.t_open * 1.4)
        p.setOpacity(fade)
        p.translate(c, c)
        p.scale(self._scale(), self._scale())
        p.translate(-c, -c)

        outer = QPolygonF([self._corner(k, R_OUT) for k in range(6)])
        path = QPainterPath()
        path.addPolygon(outer)
        path.closeSubpath()

        # the glass body: light frost, a little brighter at the top
        body = QLinearGradient(QPointF(c, c - R_OUT), QPointF(c, c + R_OUT))
        base = 34 if self.blurred else 150
        body.setColorAt(0.0, QColor(255, 255, 255, base + 26))
        body.setColorAt(0.5, QColor(240, 244, 255, base))
        body.setColorAt(1.0, QColor(225, 232, 250, base - 6))
        p.fillPath(path, QColor(18, 22, 34, 120 if self.blurred else 215))
        p.fillPath(path, body)

        # hair-thin separators and the glass edge
        p.setPen(QPen(QColor(255, 255, 255, 46), 1.0))
        for k in range(6):
            p.drawLine(self._corner(k, R_IN), self._corner(k, R_OUT))
        edge = QLinearGradient(QPointF(c, c - R_OUT), QPointF(c, c + R_OUT))
        edge.setColorAt(0.0, QColor(255, 255, 255, 170))
        edge.setColorAt(1.0, QColor(255, 255, 255, 55))
        p.setPen(QPen(QBrush(edge), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # the side under the mouse lifts out like a pane of glass (3D)
        for k in range(min(6, len(self.options))):
            g = self.glow[k]
            if g < 0.01:
                continue
            hole = QPainterPath()                   # where it lifted from looks deeper
            hole.addPolygon(self._wedge(k, R_OUT, R_IN))
            p.fillPath(hole, QColor(0, 0, 0, int(55 * g)))
            mid = math.radians(60 * k - 60)
            for i, a in enumerate((40, 26, 14)):   # soft shadow under the pane
                sh = QPainterPath()
                sh.addPolygon(self._pop(k, g * 0.8, 2 + i * 2).translated(
                    3 * g * math.cos(mid), 8 * g + i * 2))
                p.fillPath(sh, QColor(0, 0, 0, int(a * g)))
            pane = QPainterPath()
            pane.addPolygon(self._pop(k, g))
            pane.closeSubpath()
            p.fillPath(pane, QColor(18, 22, 34, int((120 if self.blurred else 215) * g)))
            lit = QLinearGradient(QPointF(c, c - R_OUT), QPointF(c, c + R_OUT))
            lit.setColorAt(0.0, QColor(255, 255, 255, int(120 * g)))
            lit.setColorAt(1.0, QColor(255, 255, 255, int(55 * g)))
            p.fillPath(pane, lit)
            rim = QLinearGradient(QPointF(c, c - R_OUT), QPointF(c, c + R_OUT))
            rim.setColorAt(0.0, QColor(255, 255, 255, int(235 * g)))
            rim.setColorAt(1.0, QColor(255, 255, 255, int(110 * g)))
            p.setPen(QPen(QBrush(rim), 1.6))
            p.drawPath(pane)

        # labels slide in when a group opens
        swap = self._ease(self.t_swap)
        p.save()
        p.setOpacity(fade * min(1.0, self.t_swap * 1.6))
        for k in range(min(6, len(self.options))):
            text, key = self.options[k]
            if key.startswith(">"):
                text += "  ›"
            mid = math.radians(60 * k - 60)
            rr = 92 + (1 - swap) * 14
            g = self.glow[k]
            spot = self._pop_transform(k, g).map(QPointF(c + rr * math.cos(mid), c + rr * math.sin(mid)))
            tx, ty = spot.x(), spot.y()
            size = 12 if len(text) <= 7 else 10
            if g > 0.5:
                size += 1
            p.setFont(QFont("Segoe UI Variable Display", size, QFont.Weight.DemiBold))
            box = QRectF(tx - 42, ty - 22, 84, 44)
            flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
            p.setPen(QColor(0, 0, 0, 70))                 # soft shadow keeps text readable
            p.drawText(box.translated(0, 1), flags, text)
            p.setPen(QColor(255, 255, 255, int(lerp(215, 255, g))))
            p.drawText(box, flags, text)
        p.restore()

        # centre: what is selected, and back / close
        hub = QPainterPath()
        hub.addPolygon(QPolygonF([self._corner(k, R_IN - 4) for k in range(6)]))
        hub.closeSubpath()
        p.fillPath(hub, QColor(255, 255, 255, int(30 + 30 * self.centre_glow)))
        p.setPen(QPen(QColor(255, 255, 255, 120), 1.0))
        p.drawPath(hub)
        p.setPen(QColor(255, 255, 255, 240))
        p.setFont(QFont("Segoe UI Variable Display", 10, QFont.Weight.Bold))
        p.drawText(QRectF(c - 44, c - 21, 88, 24), Qt.AlignmentFlag.AlignCenter, self.label)
        p.setPen(QColor(255, 255, 255, 170))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(QRectF(c - 44, c + 2, 88, 18), Qt.AlignmentFlag.AlignCenter,
                   "‹ Back" if self.stack else "Esc")

    # ---- input
    def mouseMoveEvent(self, e):
        k = self._index_at(e.position().x(), e.position().y())
        if k != self.hover:
            self.hover = k
            self.setCursor(Qt.CursorShape.PointingHandCursor if k >= 0 or k == -2
                           else Qt.CursorShape.ArrowCursor)

    def leaveEvent(self, _e):
        self.hover = -1

    def mousePressEvent(self, e):
        k = self._index_at(e.position().x(), e.position().y())
        if k >= 0:
            self.pick(k)
        elif k == -2:
            self.back()
        else:
            self.hide()

    def wheelEvent(self, e):                 # scroll walks around the hexagon
        if not self.options:
            return
        step = -1 if e.angleDelta().y() > 0 else 1
        n = min(6, len(self.options))
        self.hover = (max(self.hover, 0) + step) % n

    def keyPressEvent(self, e):
        key = e.key()
        if key == Qt.Key.Key_Escape:
            self.hide()
        elif key == Qt.Key.Key_Backspace:
            self.back()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.hover >= 0:
            self.pick(self.hover)
        elif Qt.Key.Key_1 <= key <= Qt.Key.Key_6:
            k = key - Qt.Key.Key_1
            if k < len(self.options):
                self.pick(k)

    def focusOutEvent(self, _e):
        self.hide()


# ------------------------------------------------------------------ app
def tray_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    pts = [QPointF(32 + 28 * math.cos(math.radians(60 * k - 90)),
                   32 + 28 * math.sin(math.radians(60 * k - 90))) for k in range(6)]
    path.addPolygon(QPolygonF(pts))
    path.closeSubpath()
    p.fillPath(path, ACCENT)
    p.end()
    return QIcon(pix)


class App(QObject):
    def __init__(self, qapp: QApplication):
        super().__init__()
        self.qapp = qapp
        self.menu = HexMenu()
        self.menu.chosen.connect(self.convert)
        self.files: list[Path] = []
        self.workers: list[Worker] = []
        self.tray = QSystemTrayIcon(tray_icon())
        self.tray.setToolTip("HK File: select files, then Ctrl+Alt+C or Shift + scroll")
        menu = QMenu()
        quit_action = QAction("Quit HK File", menu)
        quit_action.triggered.connect(qapp.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.show()
        self.triggers = Triggers()
        self.triggers.fired.connect(self.open_menu)
        self.tray.showMessage("HK File is running",
                              "Select files in Explorer, then press Ctrl+Alt+C or hold Shift and scroll.",
                              QSystemTrayIcon.MessageIcon.Information, 4000)

    def open_menu(self):
        if self.menu.isVisible():
            return
        files = explorer.selected_files()
        if not files:
            self.tray.showMessage("HK File", "Select one or more files in File Explorer first.",
                                  QSystemTrayIcon.MessageIcon.Information, 2500)
            return
        options = file_tools.top_menu(files)[:6]
        self.menu.resolve = lambda group, files=files: file_tools.group_menu(group, files)[:6]
        if not options:
            self.tray.showMessage("HK File", "These files can't be converted together.",
                                  QSystemTrayIcon.MessageIcon.Warning, 3000)
            return
        self.files = files
        label = files[0].suffix.upper().lstrip(".") if len(files) == 1 else f"{len(files)} files"
        self.menu.open_at(QCursor.pos(), options, label)

    def _ask(self, needs: str) -> str | None:
        """Password, watermark text or page numbers; None when cancelled."""
        if needs == "password":
            text, ok = QInputDialog.getText(None, "HK File", "Password:",
                                            QLineEdit.EchoMode.Password)
        elif needs == "text":
            text, ok = QInputDialog.getText(None, "HK File", "Watermark text:",
                                            QLineEdit.EchoMode.Normal, "CONFIDENTIAL")
        elif needs == "minutes":
            text, ok = QInputDialog.getText(None, "HK File", "Length of each part in minutes:",
                                            QLineEdit.EchoMode.Normal, "5")
        else:
            text, ok = QInputDialog.getText(None, "HK File", "Pages (e.g. 1-3, 5, 8-):")
        return text if ok and text.strip() else None

    def convert(self, key: str):
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
        worker = Worker(jobs)
        worker.done.connect(lambda outs, errs, w=worker: self.finished(w, outs, errs, title))
        self.workers.append(worker)
        self.tray.showMessage("HK File", f"{title}: working on {len(files)} file(s)...",
                              QSystemTrayIcon.MessageIcon.Information, 1500)
        worker.start()

    def finished(self, worker, outputs, errors, title):
        self.workers.remove(worker)
        if errors:
            self.tray.showMessage("HK File: something failed", "\n".join(errors)[:300],
                                  QSystemTrayIcon.MessageIcon.Warning, 6000)
        if outputs:
            names = ", ".join(Path(o).name for o in outputs[:3])
            self.tray.showMessage(f"HK File: {title} done", names[:200],
                                  QSystemTrayIcon.MessageIcon.Information, 3000)


def main():
    os.chdir(Path(__file__).resolve().parent)
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    _app = App(qapp)
    sys.exit(qapp.exec())


if __name__ == "__main__":
    main()
