"""Before / after comparison and saved versions for FC.

Versions live in a hidden ".fc-versions" folder next to the original:
v0 is the original as it was, then v1, v2, ... one per result.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import tempfile
import time
from pathlib import Path

from converters import font, kind_of

VERSIONS = ".fc-versions"


# ---------------------------------------------------------------- versions
def versions_dir(src: Path) -> Path:
    return src.parent / VERSIONS / src.stem


def save_versions(sources: list[Path], outputs: list[Path], tool: str) -> list[Path]:
    """Keep the original (once) and a copy of every result as numbered versions."""
    saved = []
    for src in sources:
        folder = versions_dir(src)
        if not folder.exists():
            folder.mkdir(parents=True)
            try:  # hide the versions folder like other app data
                ctypes.windll.kernel32.SetFileAttributesW(str(src.parent / VERSIONS), 0x2)
            except Exception:  # noqa: BLE001
                pass
        if not any(folder.glob("v0 *")):
            shutil.copy2(src, folder / f"v0 original{src.suffix}")
        n = 1 + max((int(p.name.split(" ")[0][1:]) for p in folder.iterdir()
                     if p.name[:1] == "v" and p.name.split(" ")[0][1:].isdigit()), default=0)
        stamp = time.strftime("%Y-%m-%d %H-%M")
        safe_tool = "".join(ch for ch in tool if ch.isalnum() or ch in " -_")[:30].strip() or "result"
        for out in outputs:
            out = Path(out)
            name = f"v{n} {safe_tool} {stamp}{out.suffix if out.is_file() else ''}"
            dest = folder / name
            if out.is_dir():
                shutil.copytree(out, dest)
            elif out.exists():
                shutil.copy2(out, dest)
            saved.append(dest)
            n += 1
    return saved


# ---------------------------------------------------------------- before / after
def _size(p: Path) -> int:
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size if p.exists() else 0


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _first_file(p: Path) -> Path | None:
    if p.is_dir():
        files = sorted(f for f in p.iterdir() if f.is_file())
        return files[0] if files else None
    return p


def _picture(p: Path, box: int):
    """A preview image of a file, or None when we can't draw that kind."""
    from PIL import Image

    p = _first_file(p)
    if p is None:
        return None
    kind = kind_of(p)
    try:
        if kind == "image":
            img = Image.open(p)
            img.load()
        elif kind == "pdf":
            import pymupdf
            with pymupdf.open(p) as doc:
                if doc.needs_pass:
                    return None
                pix = doc[0].get_pixmap(dpi=110)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        else:
            return None
    except Exception:  # noqa: BLE001
        return None
    img = img.convert("RGB")
    img.thumbnail((box, box))
    return img


# colour and letter of each file type, like the icons people know
TYPE_LOOK = {
    ".doc": ((43, 87, 154), "W"), ".docx": ((43, 87, 154), "W"), ".rtf": ((43, 87, 154), "W"),
    ".odt": ((43, 87, 154), "W"), ".txt": ((96, 108, 130), "TXT"),
    ".xls": ((33, 115, 70), "X"), ".xlsx": ((33, 115, 70), "X"), ".csv": ((33, 115, 70), "CSV"),
    ".ppt": ((196, 79, 42), "P"), ".pptx": ((196, 79, 42), "P"),
    ".pdf": ((200, 38, 46), "PDF"), ".zip": ((214, 160, 40), "ZIP"),
    ".mp3": ((140, 82, 200), "♪"), ".wav": ((140, 82, 200), "♪"), ".flac": ((140, 82, 200), "♪"),
    ".ogg": ((140, 82, 200), "♪"), ".m4a": ((140, 82, 200), "♪"),
    ".mp4": ((60, 120, 210), "▶"), ".mkv": ((60, 120, 210), "▶"), ".webm": ((60, 120, 210), "▶"),
    ".mov": ((60, 120, 210), "▶"), ".gif": ((60, 120, 210), "GIF"),
}


def type_icon(path: Path, box: int):
    """A document icon with a folded corner, in the colour of its file type."""
    from PIL import Image, ImageDraw

    colour, letter = TYPE_LOOK.get(path.suffix.lower(), ((110, 120, 150), path.suffix.upper().lstrip(".")[:4] or "?"))
    if path.is_dir():
        colour, letter = (214, 160, 40), "▤"
    size = int(box * 0.62)
    w, h = int(size * 0.78), size
    img = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fold = int(w * 0.28)
    page = [(4, 4), (4 + w - fold, 4), (4 + w, 4 + fold), (4 + w, 4 + h), (4, 4 + h)]
    d.polygon(page, fill=(246, 247, 251))
    d.polygon([(4 + w - fold, 4), (4 + w - fold, 4 + fold), (4 + w, 4 + fold)], fill=(205, 210, 222))
    for i in range(4):                                    # faint text lines on the page
        y = 4 + int(h * 0.30) + i * int(h * 0.09)
        d.rounded_rectangle((4 + int(w * 0.18), y, 4 + int(w * 0.82), y + max(2, h // 60)), 2, fill=(214, 218, 228))
    badge = (4 - int(w * 0.12), 4 + int(h * 0.56), 4 + int(w * 0.70), 4 + int(h * 0.90))
    d.rounded_rectangle(badge, max(4, w // 16), fill=colour)
    label = font(int((badge[3] - badge[1]) * (0.62 if len(letter) <= 1 else 0.42)), bold=True)
    d.text(((badge[0] + badge[2]) / 2, (badge[1] + badge[3]) / 2), letter, font=label,
           fill="white", anchor="mm")
    return img


def compare(before: Path, after: Path) -> Path:
    """Render a side-by-side 'before | after' card and return the PNG path."""
    from PIL import Image, ImageDraw

    box = 560
    W, H = box * 2 + 90, box + 150
    card = Image.new("RGB", (W, H), (16, 20, 34))
    draw = ImageDraw.Draw(card)
    big, small = font(26, bold=True), font(19)
    b_size, a_size = _size(before), _size(after)
    change = (a_size - b_size) / b_size * 100 if b_size else 0
    for i, (title, path, size) in enumerate((("Before", before, b_size), ("After", after, a_size))):
        x0 = 30 + i * (box + 30)
        draw.rounded_rectangle((x0, 70, x0 + box, 70 + box), 18, fill=(28, 34, 54), outline=(90, 100, 140))
        pic = _picture(path, box - 24)
        if pic is not None:
            card.paste(pic, (x0 + (box - pic.width) // 2, 70 + (box - pic.height) // 2))
        else:                                   # Word, Excel, audio...: their type icon
            icon = type_icon(path, box)
            card.paste(icon, (x0 + (box - icon.width) // 2, 70 + (box - icon.height) // 2), icon)
        draw.text((x0, 24), title, font=big, fill=(255, 255, 255))
        draw.text((x0 + 110, 30), f"{path.name[:38]}  ·  {_human(size)}", font=small, fill=(180, 188, 215))
    verdict = f"{_human(b_size)} → {_human(a_size)}   ({change:+.0f}%)"
    draw.text((W / 2, H - 38), verdict, font=big, anchor="mm",
              fill=(120, 230, 160) if change < 0 else (255, 205, 120) if change > 0 else (220, 220, 230))
    tmp = Path(tempfile.gettempdir())
    for old in tmp.glob("fc-compare-*.png"):          # tidy up cards older than a day
        try:
            if time.time() - old.stat().st_mtime > 86_400:
                old.unlink()
        except OSError:
            pass
    fd, name = tempfile.mkstemp(prefix="fc-compare-", suffix=".png")   # unique, private
    with os.fdopen(fd, "wb") as f:
        card.save(f, "PNG")
    return Path(name)
