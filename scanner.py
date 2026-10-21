"""Scan a page with the scanner the system already knows about: WIA on Windows
(built in, free), SANE's scanimage on Linux (package "sane-utils").

Windows shows its own scan dialog (paper size, colour, preview); we only save the
result as a PNG so the rest of FC can turn it into a PDF, compress it, etc.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from converters import _free_name

WIA_DEVICE_SCANNER = 1
WIA_INTENT_COLOR = 1
WIA_BIAS_QUALITY = 0x20000
WIA_FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
WIA_NO_DEVICE = -2145320939          # 0x80210015: no scanner connected
WIA_OFFLINE = -2145320954            # 0x80210005: scanner switched off or busy


class NoScanner(Exception):
    """No scanner is connected, or it is switched off."""


def _scan_sane(folder: Path) -> Path:
    exe = shutil.which("scanimage")
    if exe is None:
        raise NoScanner("install sane-utils to scan on Linux")
    out = _free_name(Path(folder) / f"Scan {time.strftime('%Y-%m-%d %H%M%S')}.png", "png", "")
    try:
        with open(out, "wb") as f:
            done = subprocess.run([exe, "--format=png", "--resolution=300", "--mode=Color"],
                                  stdout=f, stderr=subprocess.PIPE, timeout=300)
    except subprocess.TimeoutExpired as e:
        out.unlink(missing_ok=True)
        raise NoScanner from e
    if done.returncode != 0 or out.stat().st_size == 0:
        out.unlink(missing_ok=True)
        raise NoScanner(done.stderr.decode(errors="replace").strip()[:200])
    return out


def scan_to(folder: Path) -> Path | None:
    """Scan one page into folder. Returns the PNG, or None if the user cancelled."""
    if sys.platform != "win32":
        return _scan_sane(folder)
    import comtypes
    import comtypes.client

    dialog = comtypes.client.CreateObject("WIA.CommonDialog")
    try:
        image = dialog.ShowAcquireImage(WIA_DEVICE_SCANNER, WIA_INTENT_COLOR, WIA_BIAS_QUALITY,
                                        WIA_FORMAT_PNG, False, True, False)
    except comtypes.COMError as e:
        if e.hresult in (WIA_NO_DEVICE, WIA_OFFLINE):
            raise NoScanner from e
        raise
    if image is None:                # the user closed the dialog
        return None
    out = _free_name(Path(folder) / f"Scan {time.strftime('%Y-%m-%d %H%M%S')}.png", "png", "")
    image.SaveFile(str(out))
    return out
