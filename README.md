# HK File

![HK File hexagon menu](docs/preview.png)

Select files in File Explorer, press **Ctrl+Alt+C** (or hold **Shift** and scroll),
and a frosted-glass hexagon opens around the mouse with the tools for those files.
Results are saved next to the originals; nothing is overwritten and nothing is uploaded.

## Tools by file type
| Files | First hexagon (sides with › open more tools) |
|---|---|
| PDF | Split / Merge, Convert › (Word, JPG, PNG, PowerPoint, Text, Get images), Compress, Pages › (extract, remove, rotate, reverse), Security › (protect, unlock, clean data), Edit › (watermark, page numbers, repair) |
| Word | Convert › (PDF, TXT, RTF, DOCX), Compress, Split (one PDF per page) / Merge, Protect, Zip, Lock in ZIP |
| PowerPoint | Convert › (PDF, PNG, PPTX), Compress, Split (one file per slide) / Merge, Protect, Zip, Lock in ZIP |
| Excel | Convert › (PDF, XLSX, CSV), Compress, Split (one file per sheet) / Merge, Protect, Zip, Lock in ZIP |
| Images | Convert › (PNG, JPG, WEBP, PDF, ICO, BMP), Compress, Split in 4 / One PDF, Protect (locked PDF), Resize 50%, Rotate |
| Audio / video | Convert › (MP3, WAV, FLAC, OGG, M4A / MP4, WEBM, MKV, GIF), Compress, Split (parts of N minutes) / Merge, Zip, Lock in ZIP |
| Anything else | Zip, Lock in ZIP (AES-256, opens with 7-Zip or WinRAR) |

In the hexagon: click a side, or scroll / press 1-6 and Enter. The middle goes back;
Esc closes it.

## Install and run
```
pip install -r requirements.txt
```
- `HK File.bat` starts it (hexagon icon in the tray; right-click it to quit).

Needs: Python with `PyQt6 pynput comtypes Pillow PyMuPDF imageio-ffmpeg pyzipper python-pptx pdf2docx`.
Word, Excel and PowerPoint tools use Microsoft Office, with macros turned off.
