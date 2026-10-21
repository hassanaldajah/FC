"""Compress, merge, split and protect for every kind of file.

Word, Excel and PowerPoint go through Microsoft Office (macros off), media
through FFmpeg, images through Pillow, and anything else into ZIP files.
Every tool writes new files next to the source and returns their paths.
"""
from __future__ import annotations

import io
import subprocess
import zipfile
from pathlib import Path

import converters
import pdf_tools
from converters import _free_name, kind_of

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MAX_INPUT = 4 << 30              # 4 GB per input file
MAX_ZIP_MEMBERS = 20_000         # Office files are ZIPs: limits against zip bombs
MAX_ZIP_MEMBER = 512 << 20       # 512 MB unpacked per part
MAX_ZIP_TOTAL = 2 << 30          # 2 GB unpacked in total


def _folder(src: Path, tag: str) -> Path:
    return pdf_tools._folder(src, tag)


# ================================================================ any file
def zip_files(paths: list[Path], _arg: str = "") -> list[Path]:
    out = _free_name(paths[0], "zip", "" if len(paths) == 1 else " (files)")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in paths:
            z.write(p, p.name)
    return [out]


def protect_zip(paths: list[Path], password: str) -> list[Path]:
    """AES-256 encrypted ZIP; opens with 7-Zip / WinRAR and the password."""
    import pyzipper

    if len(password) < 4:
        raise ValueError("use a password of at least 4 characters")
    out = _free_name(paths[0], "zip", " (protected)")
    with pyzipper.AESZipFile(out, "w", compression=pyzipper.ZIP_DEFLATED,
                             encryption=pyzipper.WZ_AES) as z:
        z.setpassword(password.encode("utf-8"))
        for p in paths:
            z.write(p, p.name)
    return [out]


# ================================================================ images
def _img_open_rgb(path: Path):
    from PIL import Image
    img = Image.open(path)
    img.load()
    return img


def compress_image(src: Path, _arg: str = "") -> list[Path]:
    from PIL import Image

    img = _img_open_rgb(src)
    if max(img.size) > 2560:
        img.thumbnail((2560, 2560), Image.LANCZOS)
    ext = src.suffix.lower()
    if ext == ".png":
        out = _free_name(src, "png", " (compressed)")
        img.convert("RGBA").quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(out, optimize=True)
    elif ext == ".webp":
        out = _free_name(src, "webp", " (compressed)")
        img.save(out, "WEBP", quality=70, method=6)
    else:
        out = _free_name(src, "jpg", " (compressed)")
        img.convert("RGB").save(out, "JPEG", quality=70, optimize=True, progressive=True)
    if out.stat().st_size >= src.stat().st_size:
        out.unlink()
        raise ValueError("already as small as it gets")
    return [out]


def resize_half(src: Path, _arg: str = "") -> list[Path]:
    from PIL import Image

    img = _img_open_rgb(src)
    img = img.resize((max(1, img.width // 2), max(1, img.height // 2)), Image.LANCZOS)
    out = _free_name(src, src.suffix.lstrip(".").lower(), " (50%)")
    (img.convert("RGB") if out.suffix.lower() in (".jpg", ".jpeg") else img).save(out)
    return [out]


def rotate_image(src: Path, _arg: str = "") -> list[Path]:
    img = _img_open_rgb(src)
    out = _free_name(src, src.suffix.lstrip(".").lower(), " (rotated)")
    img.rotate(-90, expand=True).save(out)
    return [out]


def protect_images(paths: list[Path], password: str) -> list[Path]:
    """Images into one PDF locked with a password."""
    merged = pdf_tools.images_to_pdf(paths)[0]
    try:
        return pdf_tools.protect(merged, password)
    finally:
        merged.unlink()


def split_image(src: Path, _arg: str = "") -> list[Path]:
    """Cut an image into four quarters (handy for posters and grids)."""
    img = _img_open_rgb(src)
    folder = _folder(src, "parts")
    w, h = img.width // 2, img.height // 2
    ext = src.suffix.lower()
    for i, (x, y) in enumerate(((0, 0), (w, 0), (0, h), (w, h)), 1):
        part = img.crop((x, y, x + w, y + h))
        part.save(folder / f"{src.stem}-{i}{ext}")
    return [folder]


def watermark_image(src: Path, text: str) -> list[Path]:
    """A large, faint, diagonal line of text across the picture."""
    from PIL import Image, ImageDraw, ImageFont

    text = (text or "CONFIDENTIAL").strip()[:60]
    img = _img_open_rgb(src).convert("RGBA")
    w, h = img.size
    size = max(16, int(min(w, h) / max(5, len(text)) * 1.7))
    try:
        font = ImageFont.truetype("segoeuib.ttf", size)
    except OSError:
        font = ImageFont.load_default()
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.text((w / 2, h / 2), text, font=font, anchor="mm", fill=(255, 255, 255, 70),
              stroke_width=max(1, size // 30), stroke_fill=(0, 0, 0, 55))
    layer = layer.rotate(30, resample=Image.BICUBIC, center=(w / 2, h / 2))
    out = _free_name(src, src.suffix.lstrip(".").lower(), " (watermark)")
    result = Image.alpha_composite(img, layer)
    (result.convert("RGB") if out.suffix.lower() in (".jpg", ".jpeg", ".bmp") else result).save(out)
    return [out]


# ================================================================ Office files
def _recompress_office(src: Path, _arg: str = "") -> list[Path]:
    """docx / pptx / xlsx are ZIPs: shrink the pictures inside and repack."""
    from PIL import Image

    with zipfile.ZipFile(src) as zin:                 # refuse zip bombs before writing anything
        items = zin.infolist()
        if (len(items) > MAX_ZIP_MEMBERS or any(i.file_size > MAX_ZIP_MEMBER for i in items)
                or sum(i.file_size for i in items) > MAX_ZIP_TOTAL):
            raise ValueError("this file unpacks to something far too large")
    out = _free_name(src, src.suffix.lstrip(".").lower(), " (compressed)")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED,
                                                      compresslevel=9) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            low = item.filename.lower()
            if "/media/" in low and low.endswith((".png", ".jpg", ".jpeg")) and len(data) > 60_000:
                try:
                    img = Image.open(io.BytesIO(data))
                    img.load()
                    if max(img.size) > 1600:
                        img.thumbnail((1600, 1600), Image.LANCZOS)
                    buf = io.BytesIO()
                    if low.endswith(".png"):
                        img.save(buf, "PNG", optimize=True)
                    else:
                        img.convert("RGB").save(buf, "JPEG", quality=72, optimize=True)
                    if buf.tell() < len(data):
                        data = buf.getvalue()
                except Exception:  # noqa: BLE001 - keep the original picture
                    pass
            zout.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED)
    if out.stat().st_size >= src.stat().st_size:
        out.unlink()
        raise ValueError("already as small as it gets")
    return [out]


def _office(prog: str):
    import comtypes.client
    app = comtypes.client.CreateObject(prog)
    try:
        app.AutomationSecurity = 3            # never run macros in files we open
    except Exception:  # noqa: BLE001
        pass
    return app


# ---- Word
def merge_word(paths: list[Path], _arg: str = "") -> list[Path]:
    paths = sorted(paths, key=lambda p: p.name.lower())
    out = _free_name(paths[0], "docx", " (merged)")
    word = _office("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Add()
        rng = doc.Content
        for i, p in enumerate(paths):
            rng = doc.Content
            rng.Collapse(0)                     # end of the document
            if i:
                rng.InsertBreak(7)              # page break between files
                rng = doc.Content
                rng.Collapse(0)
            rng.InsertFile(str(p))
        doc.SaveAs2(str(out), FileFormat=16)
        doc.Close(False)
    finally:
        word.Quit()
    return [out]


def protect_word(src: Path, password: str) -> list[Path]:
    if len(password) < 4:
        raise ValueError("use a password of at least 4 characters")
    out = _free_name(src, "docx", " (protected)")
    word = _office("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False)
        doc.SaveAs2(str(out), FileFormat=16, Password=password)
        doc.Close(False)
    finally:
        word.Quit()
    return [out]


def watermark_word(src: Path, text: str) -> list[Path]:
    """Word's own kind of watermark: faint diagonal text behind every page."""
    text = (text or "CONFIDENTIAL").strip()[:60]
    out = _free_name(src, "docx", " (watermark)")
    word = _office("Word.Application")
    try:
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(src), ReadOnly=True, AddToRecentFiles=False)
        for i in range(1, doc.Sections.Count + 1):
            section = doc.Sections(i)
            page_w, page_h = section.PageSetup.PageWidth, section.PageSetup.PageHeight
            header = section.Headers(1)                   # primary header holds it
            shape = header.Shapes.AddTextEffect(0, text, "Segoe UI", 66, True, False, 0, 0)
            shape.Fill.ForeColor.RGB = 0xC0C0C0
            shape.Fill.Transparency = 0.6
            shape.Line.Visible = False
            shape.WrapFormat.Type = 3                 # behind text
            shape.RelativeHorizontalPosition = 1      # measured from the page
            shape.RelativeVerticalPosition = 1
            shape.Left = (page_w - shape.Width) / 2
            shape.Top = (page_h - shape.Height) / 2
            shape.Rotation = 315
        doc.SaveAs2(str(out), FileFormat=16)
        doc.Close(False)
    finally:
        word.Quit()
    return [out]


def watermark_slides(src: Path, text: str) -> list[Path]:
    text = (text or "CONFIDENTIAL").strip()[:60]
    out = _free_name(src, "pptx", " (watermark)")
    app = _office("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
        w, h = pres.PageSetup.SlideWidth, pres.PageSetup.SlideHeight
        for i in range(1, pres.Slides.Count + 1):
            box = pres.Slides(i).Shapes.AddTextbox(1, w * 0.1, h * 0.4, w * 0.8, h * 0.2)
            rng = box.TextFrame.TextRange
            rng.Text = text
            rng.Font.Size = max(24, int(w / max(6, len(text)) * 1.4))
            rng.Font.Bold = True
            rng.Font.Color.RGB = 0xC0C0C0
            rng.ParagraphFormat.Alignment = 2          # centred
            box.TextFrame2.TextRange.Font.Fill.Transparency = 0.6
            box.Rotation = 330
        pres.SaveAs(str(out), 24)
        pres.Close()
    finally:
        app.Quit()
    return [out]


def split_word(src: Path, _arg: str = "") -> list[Path]:
    """One PDF per page (Word has no stable page objects to cut a .docx by)."""
    pdf = converters._office_word(src, "pdf")
    try:
        return pdf_tools.split(pdf)
    finally:
        pdf.unlink()


# ---- PowerPoint
def merge_slides(paths: list[Path], _arg: str = "") -> list[Path]:
    paths = sorted(paths, key=lambda p: p.name.lower())
    out = _free_name(paths[0], "pptx", " (merged)")
    app = _office("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(paths[0]), ReadOnly=True, WithWindow=False)
        for p in paths[1:]:
            pres.Slides.InsertFromFile(str(p), pres.Slides.Count)
        pres.SaveAs(str(out), 24)
        pres.Close()
    finally:
        app.Quit()
    return [out]


def split_slides(src: Path, _arg: str = "") -> list[Path]:
    folder = _folder(src, "slides")
    app = _office("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
        count = pres.Slides.Count
        pres.Close()
        for i in range(1, count + 1):
            pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
            for j in range(count, 0, -1):
                if j != i:
                    pres.Slides(j).Delete()
            pres.SaveAs(str(folder / f"{src.stem}-{i:03d}.pptx"), 24)
            pres.Close()
    finally:
        app.Quit()
    return [folder]


def protect_slides(src: Path, password: str) -> list[Path]:
    if len(password) < 4:
        raise ValueError("use a password of at least 4 characters")
    out = _free_name(src, "pptx", " (protected)")
    app = _office("PowerPoint.Application")
    try:
        pres = app.Presentations.Open(str(src), ReadOnly=True, WithWindow=False)
        pres.Password = password
        pres.SaveAs(str(out), 24)
        pres.Close()
    finally:
        app.Quit()
    return [out]


# ---- Excel
def merge_sheets(paths: list[Path], _arg: str = "") -> list[Path]:
    paths = sorted(paths, key=lambda p: p.name.lower())
    out = _free_name(paths[0], "xlsx", " (merged)")
    excel = _office("Excel.Application")
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        target = excel.Workbooks.Add()
        first_blank = target.Worksheets(1)
        for p in paths:
            book = excel.Workbooks.Open(str(p), UpdateLinks=0, ReadOnly=True)
            for k in range(1, book.Worksheets.Count + 1):
                book.Worksheets(k).Copy(After=target.Worksheets(target.Worksheets.Count))
            book.Close(False)
        first_blank.Delete()
        target.SaveAs(str(out), 51)
        target.Close(False)
    finally:
        excel.Quit()
    return [out]


def split_sheets(src: Path, _arg: str = "") -> list[Path]:
    folder = _folder(src, "sheets")
    excel = _office("Excel.Application")
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        book = excel.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
        for k in range(1, book.Worksheets.Count + 1):
            sheet = book.Worksheets(k)
            name = "".join(ch for ch in sheet.Name if ch not in '\\/:*?"<>|') or f"sheet{k}"
            sheet.Copy()                       # copies into a new workbook
            new = excel.ActiveWorkbook
            new.SaveAs(str(folder / f"{src.stem}-{name}.xlsx"), 51)
            new.Close(False)
        book.Close(False)
    finally:
        excel.Quit()
    return [folder]


def protect_sheets(src: Path, password: str) -> list[Path]:
    if len(password) < 4:
        raise ValueError("use a password of at least 4 characters")
    out = _free_name(src, "xlsx", " (protected)")
    excel = _office("Excel.Application")
    try:
        excel.Visible = False
        excel.DisplayAlerts = False
        book = excel.Workbooks.Open(str(src), UpdateLinks=0, ReadOnly=True)
        book.SaveAs(str(out), 51, password)
        book.Close(False)
    finally:
        excel.Quit()
    return [out]


# ================================================================ audio / video
def _ff(args: list[str]) -> None:
    import imageio_ffmpeg
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                    "-n", *args], check=True, timeout=7200, creationflags=NO_WINDOW)


def compress_media(src: Path, _arg: str = "") -> list[Path]:
    if kind_of(src) == "video":
        out = _free_name(src, "mp4", " (compressed)")
        _ff(["-i", str(src), "-c:v", "libx264", "-crf", "28", "-preset", "medium",
             "-vf", "scale='min(1280,iw)':-2", "-c:a", "aac", "-b:a", "96k", str(out)])
    else:
        out = _free_name(src, "mp3", " (compressed)")
        _ff(["-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "96k", str(out)])
    if out.stat().st_size >= src.stat().st_size:
        out.unlink()
        raise ValueError("already as small as it gets")
    return [out]


def merge_media(paths: list[Path], _arg: str = "") -> list[Path]:
    paths = sorted(paths, key=lambda p: p.name.lower())
    video = any(kind_of(p) == "video" for p in paths)
    out = _free_name(paths[0], "mp4" if video else "mp3", " (merged)")
    args: list[str] = []
    for p in paths:
        args += ["-i", str(p)]
    n = len(paths)
    if video:
        scale = "".join(f"[{i}:v]scale=1280:720:force_original_aspect_ratio=decrease,"
                        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}];" for i in range(n))
        streams = "".join(f"[v{i}][{i}:a]" for i in range(n))
        graph = f"{scale}{streams}concat=n={n}:v=1:a=1[v][a]"
        args += ["-filter_complex", graph, "-map", "[v]", "-map", "[a]",
                 "-c:v", "libx264", "-crf", "23", "-c:a", "aac", str(out)]
    else:
        streams = "".join(f"[{i}:a]" for i in range(n))
        args += ["-filter_complex", f"{streams}concat=n={n}:v=0:a=1[a]", "-map", "[a]",
                 "-c:a", "libmp3lame", "-q:a", "2", str(out)]
    _ff(args)
    return [out]


def split_media(src: Path, minutes: str) -> list[Path]:
    try:
        seconds = max(5, int(float(minutes) * 60))
    except ValueError:
        raise ValueError("type the length of each part in minutes, e.g. 5") from None
    folder = _folder(src, "parts")
    _ff(["-i", str(src), "-f", "segment", "-segment_time", str(seconds), "-c", "copy",
         "-reset_timestamps", "1", str(folder / f"{src.stem}-%03d{src.suffix.lower()}")])
    return [folder]


# ================================================================ registry
# key: (label, function, needs, scope)   needs: None|"password"|"text"|"pages"|"minutes"
TOOLS = dict(pdf_tools.TOOLS)
TOOLS.update({
    "zip": ("Zip", zip_files, None, "all"),
    "zip_lock": ("Lock in ZIP", protect_zip, "password", "all"),
    "img_compress": ("Compress", compress_image, None, "each"),
    "img_resize": ("Resize 50%", resize_half, None, "each"),
    "img_rotate": ("Rotate ↻", rotate_image, None, "each"),
    "img_split": ("Split in 4", split_image, None, "each"),
    "img_protect": ("Protect", protect_images, "password", "all"),
    "img_watermark": ("Watermark", watermark_image, "text", "each"),
    "word_watermark": ("Watermark", watermark_word, "text", "each"),
    "ppt_watermark": ("Watermark", watermark_slides, "text", "each"),
    "office_compress": ("Compress", _recompress_office, None, "each"),
    "word_merge": ("Merge", merge_word, None, "all"),
    "word_split": ("Split", split_word, None, "each"),
    "word_protect": ("Protect", protect_word, "password", "each"),
    "ppt_merge": ("Merge", merge_slides, None, "all"),
    "ppt_split": ("Split", split_slides, None, "each"),
    "ppt_protect": ("Protect", protect_slides, "password", "each"),
    "xl_merge": ("Merge", merge_sheets, None, "all"),
    "xl_split": ("Split", split_sheets, None, "each"),
    "xl_protect": ("Protect", protect_sheets, "password", "each"),
    "media_compress": ("Compress", compress_media, None, "each"),
    "media_merge": ("Merge", merge_media, None, "all"),
    "media_split": ("Split", split_media, "minutes", "each"),
})

OFFICE_KEYS = {
    "word": ("word_merge", "word_split", "word_protect"),
    "slides": ("ppt_merge", "ppt_split", "ppt_protect"),
    "sheet": ("xl_merge", "xl_split", "xl_protect"),
}


def top_menu(paths: list[Path]) -> list[tuple[str, str]]:
    """The first hexagon for the selected files: (label, key); '>' opens a group."""
    kinds = {kind_of(p) for p in paths}
    many = len(paths) > 1
    kind = kinds.pop() if len(kinds) == 1 else None
    if kind == "pdf":
        return pdf_tools.pdf_menu(many)
    if kind in OFFICE_KEYS:
        merge_k, split_k, protect_k = OFFICE_KEYS[kind]
        sixth = {"word": ("Watermark", "word_watermark"),
                 "slides": ("Watermark", "ppt_watermark")}.get(kind, ("Zip", "zip"))
        return [("Convert", ">Convert"), ("Compress", "office_compress"),
                ("Merge", merge_k) if many else ("Split", split_k),
                ("Protect", protect_k), sixth, ("Lock in ZIP", "zip_lock")] + (
            [("Zip", "zip")] if kind in ("word", "slides") else [])
    if kind == "image":
        return [("Convert", ">Convert"), ("Compress", "img_compress"),
                ("One PDF", "img_pdf") if many else ("Split in 4", "img_split"),
                ("Protect", "img_protect"), ("Edit", ">ImageEdit"), ("Zip", "zip"),
                ("Lock in ZIP", "zip_lock")]
    if kind in ("audio", "video"):
        return [("Convert", ">Convert"), ("Compress", "media_compress"),
                ("Merge", "media_merge") if many else ("Split", "media_split"),
                ("Lock in ZIP", "zip_lock"), ("Zip", "zip")]
    if many and kinds <= {"audio", "video"} and None not in kinds:   # mixed media
        return [("Merge", "media_merge"), ("Zip", "zip"), ("Lock in ZIP", "zip_lock")]
    return [("Zip", "zip"), ("Lock in ZIP", "zip_lock")]           # any other files


def group_menu(group: str, paths: list[Path]) -> list[tuple[str, str]]:
    if group == "ImageEdit":
        return [("Watermark", "img_watermark"), ("Resize 50%", "img_resize"), ("Rotate ↻", "img_rotate")]
    if group == "Convert" and {kind_of(p) for p in paths} != {"pdf"}:
        return [(t.upper(), "fmt:" + t) for t in converters.targets_for(paths)]
    return pdf_tools.group_menu(group)


def _checked(paths: list[Path]) -> list[Path]:
    """Absolute, existing, regular files of a sane size; anything else is refused."""
    out = []
    for p in paths:
        p = Path(p).resolve()
        if not p.is_file():
            raise ValueError(f"not a file: {p.name}")
        if p.stat().st_size > MAX_INPUT:
            raise ValueError(f"{p.name} is larger than {MAX_INPUT >> 30} GB")
        out.append(p)
    return out


def run(key: str, paths: list[Path], arg: str = "") -> list[Path]:
    paths = _checked(paths)
    if key.startswith("fmt:"):
        return [converters.convert(p, key[4:]) for p in paths]
    _label, tool, _needs, scope = TOOLS[key]
    if scope == "all":
        return tool(paths, arg)
    outputs: list[Path] = []
    for p in paths:
        outputs.extend(tool(p, arg))
    return outputs
