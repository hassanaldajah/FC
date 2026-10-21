"""Which files are selected in the File Explorer window in front."""
from __future__ import annotations

import ctypes
import sys
import warnings
from pathlib import Path

IS_WIN = sys.platform == "win32"
user32 = ctypes.windll.user32 if IS_WIN else None      # Linux has no File Explorer to ask


def _class_name(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def foreground_is_explorer() -> bool:
    if not IS_WIN:
        return False
    return _class_name(user32.GetForegroundWindow()) in ("CabinetWClass", "ExploreWClass")


def selected_files() -> list[Path]:
    """Selected files (not folders) of the active Explorer window, or []."""
    if not IS_WIN:
        return []
    hwnd = user32.GetForegroundWindow()
    if _class_name(hwnd) not in ("CabinetWClass", "ExploreWClass"):
        return []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import comtypes.client
    try:
        shell = comtypes.client.CreateObject("Shell.Application")
        windows = shell.Windows()
        for i in range(windows.Count):
            win = windows.Item(i)
            if win is None or int(win.HWND) != hwnd:
                continue
            items = win.Document.SelectedItems()
            found = []
            for j in range(items.Count):
                item = items.Item(j)
                if item is not None and not item.IsFolder:
                    found.append(Path(item.Path))
            return found
    except Exception:  # noqa: BLE001 - Explorer can be busy or closing
        return []
    return []
