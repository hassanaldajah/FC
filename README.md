# HK File

![HK File octagon menu](docs/preview.png)

A free Windows tool that converts, compresses and edits files from a glass octagon on your screen.
Drop files on it, pick **Choose files**, or select files in File Explorer and press **Ctrl+Alt+C**
(or hold **Shift** and scroll): the octagon turns into the tools for those files.
Before a tool runs it asks where to save the result. Your original file is never overwritten.

**HK File never connects to the internet.** Every tool runs on your own computer.

## Download and verify
1. Open the [latest release](https://github.com/hassanaldajah/HK-File/releases/latest) and download
   `HKFile-<version>-win64.exe` and its `.sha256` file.
2. Check the checksum in PowerShell. The two values must be the same:
   ```powershell
   (Get-FileHash .\HKFile-1.0.0-win64.exe -Algorithm SHA256).Hash.ToLower()
   Get-Content .\HKFile-1.0.0-win64.exe.sha256
   ```
3. Optional, stronger: prove the exe was built by this repository's GitHub Actions from the
   tagged source code (needs the free [GitHub CLI](https://cli.github.com/)):
   ```powershell
   gh attestation verify .\HKFile-1.0.0-win64.exe --repo hassanaldajah/HK-File
   ```
4. VirusTotal scan of v1.0.0: _link added after the release is published_.

### "Windows protected your PC"
The exe is not code-signed (a signing certificate costs money every year, and this project is free).
Windows SmartScreen therefore warns about any new unsigned program until enough people have run it.
If the checksum above matches, click **More info → Run anyway**. You only need to do this once.

## What it does
| Files | Sides of the octagon (› opens more tools) |
|---|---|
| Start | Choose files, Scan, Recent ›, PDF, Images, Office, Media, Other files |
| PDF | Split / Merge, Convert › (Word, JPG, PNG, PowerPoint, Text, Get images), Compress, Pages ›, Security ›, Edit › (watermark, page numbers, repair), Zip |
| Word / PowerPoint | Convert ›, Compress, Split / Merge, Protect, Watermark, Lock in ZIP, Zip |
| Excel | Convert ›, Compress, Split / Merge, Protect, Zip, Lock in ZIP |
| Images | Convert ›, Compress, Split in 4 / One PDF, Protect, Edit › (watermark, resize, rotate), Zip, Lock in ZIP |
| Audio / video | Convert ›, Compress, Split / Merge, Lock in ZIP, Zip |
| Anything else | Zip, Lock in ZIP (AES-256, opens with 7-Zip or WinRAR) |

- **Scan** uses the scanner Windows already knows (WIA): Windows' own scan window opens, the page is
  saved as a PNG, and the octagon offers the image tools (for example Convert › PDF).
- **Recent › Compare** shows a before / after card with both sizes and the change in percent.
- **Recent › Versions** opens the hidden `.hkfile-versions` folder: `v0` is the original, then one
  version per result, so you can always go back.

Keys: arrows or the mouse wheel move around the sides, Enter picks, 1-8 pick directly, Tab also
reaches the centre and the – / × buttons, Esc closes, Backspace goes back. Drag the centre to move it.
With Windows' "Animation effects" setting off, the octagon appears without motion.

## Safety
- Word, Excel and PowerPoint files are opened with macros turned off and links not refreshed.
- Files that unpack to more than 2 GB (zip bombs) and inputs over 4 GB are refused.
- Found a security problem? See [SECURITY.md](SECURITY.md).

## Run from source
```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --require-hashes -r requirements.txt
.venv\Scripts\pythonw hkfile.py
```
Office tools need Microsoft Office installed. `requirements.in` lists the direct dependencies;
`requirements.txt` pins every package with its hashes (rebuild it with `tools\lock.py`).

## Build the exe yourself
```powershell
.venv\Scripts\python -m pip install --require-hashes -r requirements-build.txt
.venv\Scripts\python -m PyInstaller --clean --noconfirm hkfile.spec
```
The result is `dist\HK File.exe`. Releases are built the same way by
[.github/workflows/release.yml](.github/workflows/release.yml) when a `v*` tag is pushed.

Icons: [Lucide](https://lucide.dev) (ISC licence, see `icons/LICENSE-lucide.txt`).
