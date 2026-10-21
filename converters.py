"""File conversions used by HK File.

Every converter takes a source path and a target extension and returns the
path of the file it wrote, next to the source and never over an existing file.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

IMAGE_IN = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".ico"}
AUDIO_IN = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus"}
VIDEO_IN = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".flv", ".m4v"}
WORD_IN = {".doc", ".docx", ".rtf", ".odt"}
SLIDES_IN = {".ppt", ".pptx", ".odp"}
SHEET_IN = {".xls", ".xlsx", ".ods", ".csv"}

# up to six targets per kind: one per side of the hexagon
TARGETS = {
    "image": ["png", "jpg", "webp", "pdf", "ico", "bmp"],
    "pdf": ["png", "jpg", "docx", "txt"],
    "word": ["pdf", "txt", "docx", "rtf"],
    "slides": ["pdf", "png", "pptx"],
    "sheet": ["pdf", "xlsx", "csv"],
    "audio": ["mp3", "wav", "flac", "ogg", "m4a"],
    "video": ["mp4", "webm", "mkv", "gif", "mp3"],
}


def kind_of(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in IMAGE_IN:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in WORD_IN:
        return "word"
    if ext in SLIDES_IN:
        return "slides"
    if ext in SHEET_IN:
        return "sheet"
    if ext in AUDIO_IN:
        return "audio"
    if ext in VIDEO_IN:
        return "video"
    return None


def targets_for(paths: list[Path]) -> list[str]:
    """Formats every selected file can become (the same file type is left out)."""
    common: list[str] | None = None
    for path in paths:
        kind = kind_of(path)
        if kind is None:
            return []
        own = path.suffix.lower().lstrip(".")
        options = [t for t in TARGETS[kind] if t != own and not (own == "jpeg" and t == "jpg")]
        common = options if common is None else [t for t in common if t in options]
    return (common or [])[:7]


def _free_name(src: Path, ext: str, suffix: str = "") -> Path:
    out = src.with_name(f"{src.stem}{suffix}.{ext}")
    n = 2
    while out.exists():
        out = src.with_name(f"{src.stem}{suffix} ({n}).{ext}")
        n += 1
    return out


# ---------------------------------------------------------------- images
def _image(src: Path, ext: str) -> Path:
    from PIL import Image

    out = _free_name(src, ext)
    with Image.open(src) as img:
        if ext in ("jpg", "pdf", "bmp") and img.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", img.size, (255, 255, 255))
            rgba = img.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
        if ext == "ico":
            img.convert("RGBA").save(out, sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])
        elif ext == "jpg":
            img.convert("RGB").save(out, "JPEG", quality=92)
        elif ext == "pdf":
            img.convert("RGB").save(out, "PDF", resolution=150)
        else:
            img.save(out)
    return out


# ---------------------------------------------------------------- pdf
def _pdf(src: Path, ext: str) -> Path:
    import pymupdf

    if ext == "docx":
        from pdf_tools import to_word
        return to_word(src)[0]
    doc = pymupdf.open(src)
    try:
        if ext == "txt":
            out = _free_name(src, "txt")
            out.write_text("\n\n".join(page.get_text() for page in doc), encoding="utf-8")
            return out
        # one image per page; several pages go into their own folder
        if doc.page_count == 1:
            out = _free_name(src, ext)
            doc[0].get_pixmap(dpi=150).save(out)
            return out
        folder = src.with_name(f"{src.stem} ({ext})")
        n = 2
        while folder.exists():
            folder = src.with_name(f"{src.stem} ({ext} {n})")
            n += 1
        folder.mkdir()
        for i, page in enumerate(doc, 1):
            page.get_pixmap(dpi=150).save(folder / f"{src.stem}-{i:03d}.{ext}")
        return folder
    finally:
        doc.close()


# ---------------------------------------------------------------- office (needs MS Office)
WORD_FORMATS = {"pdf": 17, "docx": 16, "txt": 2, "rtf": 6}
PPT_FORMATS = {"pdf": 32, "pptx": 24, "png": 18}
XL_FORMATS = {"xlsx": 51, "csv": 6}


def _office_word(src: Path, ext: str) -> Path:
    import comtypes.client

    out = _free_name(src, ext)
    word = comtypes.client.CreateObject("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        word.AutomationSecurity = 3          # never run macros in files we open
        doc = word.Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False,
                                  ConfirmConversions=False)
        try:
            doc.SaveAs2(str(out), FileFormat=WORD_FORMATS[ext])
        finally:
            doc.Close(False)
    finally:
        word.Quit()
    return out


def _office_slides(src: Path, ext: str) -> Path:
    import comtypes.client

    out = _free_name(src, ext) if ext != "png" else src.with_name(f"{src.stem} (png)")
    app = comtypes.client.CreateObject("PowerPoint.Application")
    try:
        app.AutomationSecurity = 3
        pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
        try:
            pres.SaveAs(str(out), PPT_FORMATS[ext])   # png: one image per slide in a folder
        finally:
            pres.Close()
    finally:
        app.Quit()
    return out


def _office_sheet(src: Path, ext: str) -> Path:
    import comtypes.client

    out = _free_name(src, ext)
    excel = comtypes.client.CreateObject("Excel.Application")
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 3
        book = excel.Workbooks.Open(str(src), ReadOnly=True)
        try:
            if ext == "pdf":
                book.ExportAsFixedFormat(0, str(out))
            else:
                book.SaveAs(str(out), XL_FORMATS[ext])
        finally:
            book.Close(False)
    finally:
        excel.Quit()
    return out


# ---------------------------------------------------------------- audio / video
def _ffmpeg(src: Path, ext: str) -> Path:
    import imageio_ffmpeg

    out = _free_name(src, ext)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
           "-n", "-i", str(src)]
    if ext == "gif":
        cmd += ["-vf", "fps=12,scale=480:-1:flags=lanczos", "-loop", "0"]
    elif ext == "mp3":
        cmd += ["-vn", "-q:a", "2"]
    elif ext in ("wav", "flac", "ogg", "m4a"):
        cmd += ["-vn"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True, timeout=3600,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out


def convert(src: Path, ext: str) -> Path:
    kind = kind_of(src)
    if kind == "image":
        return _image(src, ext)
    if kind == "pdf":
        return _pdf(src, ext)
    if kind == "word":
        return _office_word(src, ext)
    if kind == "slides":
        return _office_slides(src, ext)
    if kind == "sheet":
        return _office_sheet(src, ext)
    if kind in ("audio", "video"):
        return _ffmpeg(src, ext)
    raise ValueError(f"Cannot convert {src.name}")
