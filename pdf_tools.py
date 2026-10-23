"""PDF tools for FC: organise, compress, protect, edit and convert.

Every tool writes new files next to the source and returns their paths. The
originals are never changed.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from converters import _free_name

# PyMuPDF is imported inside the tools that use it: it takes about a second to load, and
# FC should open at once.
if TYPE_CHECKING:
    import pymupdf


def _folder(src: Path, tag: str) -> Path:
    folder = src.with_name(f"{src.stem} ({tag})")
    n = 2
    while folder.exists():
        folder = src.with_name(f"{src.stem} ({tag} {n})")
        n += 1
    folder.mkdir()
    return folder


def _open(src: Path, password: str = "") -> pymupdf.Document:
    import pymupdf

    doc = pymupdf.open(src)
    if doc.needs_pass and not doc.authenticate(password or ""):
        doc.close()
        raise ValueError("this PDF has a password; use Security > Unlock first")
    return doc


def _save(doc: pymupdf.Document, out: Path, **kw) -> Path:
    doc.save(out, garbage=4, deflate=True, **kw)
    return out


def parse_pages(text: str, count: int) -> list[int]:
    """'1-3, 5, 8-' -> zero-based page numbers inside the document."""
    pages: list[int] = []
    for part in re.split(r"[,\s]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)", part)
        if m:
            a = int(m.group(1) or 1)
            b = int(m.group(2) or count)
            pages.extend(range(a, b + 1))
        elif part.isdigit():
            pages.append(int(part))
        else:
            raise ValueError(f"'{part}' is not a page number")
    result = [p - 1 for p in pages if 1 <= p <= count]
    if not result:
        raise ValueError("no valid page numbers")
    return list(dict.fromkeys(result))


# ---------------------------------------------------------------- organise
def merge(paths: list[Path], _arg: str = "") -> list[Path]:
    import pymupdf

    paths = sorted(paths, key=lambda p: p.name.lower())
    out = _free_name(paths[0], "pdf", " (merged)")
    merged = pymupdf.open()
    for path in paths:
        with _open(path) as doc:
            merged.insert_pdf(doc)
    _save(merged, out)
    merged.close()
    return [out]


def split(src: Path, _arg: str = "") -> list[Path]:
    import pymupdf

    folder = _folder(src, "pages")
    with _open(src) as doc:
        for i in range(doc.page_count):
            part = pymupdf.open()
            part.insert_pdf(doc, from_page=i, to_page=i)
            _save(part, folder / f"{src.stem}-{i + 1:03d}.pdf")
            part.close()
    return [folder]


def extract_pages(src: Path, pages: str) -> list[Path]:
    with _open(src) as doc:
        doc.select(parse_pages(pages, doc.page_count))
        return [_save(doc, _free_name(src, "pdf", " (extract)"))]


def remove_pages(src: Path, pages: str) -> list[Path]:
    with _open(src) as doc:
        drop = set(parse_pages(pages, doc.page_count))
        keep = [i for i in range(doc.page_count) if i not in drop]
        if not keep:
            raise ValueError("that would remove every page")
        doc.select(keep)
        return [_save(doc, _free_name(src, "pdf", " (pages removed)"))]


def _rotate(src: Path, degrees: int) -> list[Path]:
    with _open(src) as doc:
        for page in doc:
            page.set_rotation((page.rotation + degrees) % 360)
        return [_save(doc, _free_name(src, "pdf", " (rotated)"))]


def rotate_right(src, _a=""): return _rotate(src, 90)
def rotate_left(src, _a=""): return _rotate(src, 270)
def rotate_180(src, _a=""): return _rotate(src, 180)


def reverse(src: Path, _arg: str = "") -> list[Path]:
    with _open(src) as doc:
        doc.select(list(range(doc.page_count - 1, -1, -1)))
        return [_save(doc, _free_name(src, "pdf", " (reversed)"))]


# ---------------------------------------------------------------- optimise
def compress(src: Path, _arg: str = "") -> list[Path]:
    out = _free_name(src, "pdf", " (compressed)")
    with _open(src) as doc:
        try:  # shrink big images: down to 120 dpi, JPEG quality 70
            doc.rewrite_images(dpi_threshold=150, dpi_target=120, quality=70)
        except Exception:  # noqa: BLE001 - older PyMuPDF: plain clean-up only
            pass
        doc.subset_fonts()
        doc.save(out, garbage=4, deflate=True, clean=True, deflate_images=True,
                 deflate_fonts=True, use_objstms=1)
    if out.stat().st_size >= src.stat().st_size:   # never hand back a bigger file
        out.unlink()
        raise ValueError("this PDF is already as small as it gets")
    return [out]


def repair(src: Path, _arg: str = "") -> list[Path]:
    with _open(src) as doc:
        return [_save(doc, _free_name(src, "pdf", " (repaired)"), clean=True)]


# ---------------------------------------------------------------- security
def protect(src: Path, password: str) -> list[Path]:
    import pymupdf

    if len(password) < 4:
        raise ValueError("use a password of at least 4 characters")
    with _open(src) as doc:
        out = _free_name(src, "pdf", " (protected)")
        doc.save(out, garbage=4, deflate=True, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 owner_pw=password, user_pw=password,
                 permissions=pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_COPY)
        return [out]


def unlock(src: Path, password: str) -> list[Path]:
    import pymupdf

    doc = pymupdf.open(src)
    try:
        if doc.needs_pass and not doc.authenticate(password or ""):
            raise ValueError("wrong password")
        out = _free_name(src, "pdf", " (unlocked)")
        doc.save(out, garbage=4, deflate=True, encryption=pymupdf.PDF_ENCRYPT_NONE)
        return [out]
    finally:
        doc.close()


def strip_metadata(src: Path, _arg: str = "") -> list[Path]:
    with _open(src) as doc:
        doc.set_metadata({})
        doc.del_xml_metadata()
        return [_save(doc, _free_name(src, "pdf", " (clean)"))]


# ---------------------------------------------------------------- edit
def watermark(src: Path, text: str) -> list[Path]:
    import pymupdf

    text = (text or "CONFIDENTIAL").strip()[:60]
    with _open(src) as doc:
        for page in doc:
            r = page.rect
            size = max(18, min(r.width, r.height) / max(6, len(text)) * 1.6)
            centre = pymupdf.Point(r.width / 2, r.height / 2)
            width = pymupdf.get_text_length(text, fontname="helv", fontsize=size)
            page.insert_text(pymupdf.Point(centre.x - width / 2, centre.y + size / 3), text,
                             fontsize=size, fontname="helv", color=(0.85, 0.1, 0.15),
                             fill_opacity=0.18, overlay=True,
                             morph=(centre, pymupdf.Matrix(-45)))
        return [_save(doc, _free_name(src, "pdf", " (watermark)"))]


def page_numbers(src: Path, _arg: str = "") -> list[Path]:
    import pymupdf

    with _open(src) as doc:
        total = doc.page_count
        for i, page in enumerate(doc, 1):
            label = f"{i} / {total}"
            r = page.rect
            width = pymupdf.get_text_length(label, fontname="helv", fontsize=10)
            page.insert_text(pymupdf.Point((r.width - width) / 2, r.height - 24), label,
                             fontsize=10, fontname="helv", color=(0.35, 0.35, 0.4))
        return [_save(doc, _free_name(src, "pdf", " (numbered)"))]


# ---------------------------------------------------------------- convert
def to_images(src: Path, ext: str) -> list[Path]:
    from converters import _pdf
    return [_pdf(src, ext)]


def to_jpg(src, _a=""): return to_images(src, "jpg")
def to_png(src, _a=""): return to_images(src, "png")


def to_txt(src: Path, _arg: str = "") -> list[Path]:
    with _open(src) as doc:
        out = _free_name(src, "txt")
        out.write_text("\n\n".join(p.get_text() for p in doc), encoding="utf-8")
        return [out]


def to_word(src: Path, _arg: str = "") -> list[Path]:
    """PDF to an editable .docx that keeps tables, images, columns and fonts.

    pdf2docx (MIT) reads where every text block, table line and picture sits on
    the page and rebuilds them in Word. If it fails, Word's own PDF import is
    the fallback."""
    out = _free_name(src, "docx")
    try:
        import logging
        from pdf2docx import Converter

        logging.getLogger("pdf2docx").setLevel(logging.ERROR)
        with _open(src):                        # stops at a password first
            pass
        cv = Converter(str(src))
        try:
            cv.convert(str(out))
        finally:
            cv.close()
        return [out]
    except ValueError:
        raise
    except Exception:  # noqa: BLE001 - fall back to Microsoft Word
        if out.exists():
            out.unlink()
        from converters import _office_word
        return [_office_word(src, "docx")]


def to_pptx(src: Path, _arg: str = "") -> list[Path]:
    from pptx import Presentation
    from pptx.util import Emu

    out = _free_name(src, "pptx")
    with _open(src) as doc:
        first = doc[0].rect
        pres = Presentation()
        pres.slide_width = Emu(int(first.width * 12700))
        pres.slide_height = Emu(int(first.height * 12700))
        blank = pres.slide_layouts[6]
        tmp = _folder(src, "tmp-slides")
        try:
            for i, page in enumerate(doc):
                img = tmp / f"{i}.png"
                page.get_pixmap(dpi=150).save(img)
                slide = pres.slides.add_slide(blank)
                slide.shapes.add_picture(str(img), 0, 0, pres.slide_width, pres.slide_height)
            pres.save(out)
        finally:
            for f in tmp.iterdir():
                f.unlink()
            tmp.rmdir()
    return [out]


def extract_images(src: Path, _arg: str = "") -> list[Path]:
    folder = _folder(src, "images")
    count = 0
    with _open(src) as doc:
        seen = set()
        for page in doc:
            for info in page.get_images(full=True):
                xref = info[0]
                if xref in seen:
                    continue
                seen.add(xref)
                data = doc.extract_image(xref)
                count += 1
                (folder / f"{src.stem}-img{count:03d}.{data['ext']}").write_bytes(data["image"])
    if not count:
        folder.rmdir()
        raise ValueError("no images inside this PDF")
    return [folder]


def images_to_pdf(paths: list[Path], _arg: str = "") -> list[Path]:
    from PIL import Image

    paths = sorted(paths, key=lambda p: p.name.lower())
    out = _free_name(paths[0], "pdf", " (images)")
    pages = []
    for path in paths:
        with Image.open(path) as img:
            pages.append(img.convert("RGB"))
    pages[0].save(out, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    return [out]


# ---------------------------------------------------------------- the menu
# (label, tool, needs: None | "password" | "text" | "pages", works on: "each" | "all")
TOOLS = {
    "merge": ("Merge", merge, None, "all"),
    "split": ("Split", split, None, "each"),
    "extract": ("Extract pages", extract_pages, "pages", "each"),
    "remove": ("Remove pages", remove_pages, "pages", "each"),
    "rot_r": ("Rotate ↻", rotate_right, None, "each"),
    "rot_l": ("Rotate ↺", rotate_left, None, "each"),
    "rot_180": ("Rotate 180", rotate_180, None, "each"),
    "reverse": ("Reverse", reverse, None, "each"),
    "compress": ("Compress", compress, None, "each"),
    "repair": ("Repair", repair, None, "each"),
    "protect": ("Protect", protect, "password", "each"),
    "unlock": ("Unlock", unlock, "password", "each"),
    "strip": ("Clean data", strip_metadata, None, "each"),
    "watermark": ("Watermark", watermark, "text", "each"),
    "numbers": ("Page numbers", page_numbers, None, "each"),
    "to_jpg": ("JPG", to_jpg, None, "each"),
    "to_png": ("PNG", to_png, None, "each"),
    "to_word": ("Word", to_word, None, "each"),
    "to_txt": ("Text", to_txt, None, "each"),
    "to_pptx": ("PowerPoint", to_pptx, None, "each"),
    "images": ("Get images", extract_images, None, "each"),
    "img_pdf": ("One PDF", images_to_pdf, None, "all"),
}

GROUPS = {
    "Convert": ["to_word", "to_jpg", "to_png", "to_pptx", "to_txt", "images"],
    "Pages": ["extract", "remove", "rot_r", "rot_l", "rot_180", "reverse"],
    "Security": ["protect", "unlock", "strip"],
    "Edit": ["watermark", "numbers", "repair"],
}


def pdf_menu(many: bool) -> list[tuple[str, str]]:
    """Top hexagon for PDFs: (label, key). Keys starting with '>' open a group."""
    first = ("Merge", "merge") if many else ("Split", "split")
    return [first, ("Convert", ">Convert"), ("Compress", "compress"),
            ("Pages", ">Pages"), ("Security", ">Security"), ("Edit", ">Edit"), ("Zip", "zip")]


def group_menu(name: str) -> list[tuple[str, str]]:
    return [(TOOLS[k][0], k) for k in GROUPS[name]]


def run(key: str, paths: list[Path], arg: str = "") -> list[Path]:
    _label, tool, _needs, scope = TOOLS[key]
    if scope == "all":
        return tool(paths, arg)
    outputs: list[Path] = []
    for path in paths:
        outputs.extend(tool(path, arg))
    return outputs
