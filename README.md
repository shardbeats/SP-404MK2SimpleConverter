# SP-404 MK2 Simple Converter

Convert your sound libraries (drum kits, sample packs) to a format compatible with the **Roland SP-404 MK2** sampler.

## Target format (SP-404 MK2)
- **Sample rates:** 16 kHz, 22.05 kHz, 32 kHz, 44.1 kHz, 48 kHz, 88.2 kHz, 96 kHz, 176.4 kHz, 192 kHz
- **Bit depth:** 16-bit or 24-bit
- **Channels:** Mono (1) or Stereo (2)
- **Codec:** PCM signed 16-bit or 24-bit little-endian or big-endian
- **Container:** WAV (recommended: 44.1 kHz, 16-bit, stereo)

## How files are handled
- **Already compatible:** automatically copied (no conversion) when they already meet the requirements.
- **Needs conversion:** converted to 44.1 kHz, 16-bit, stereo PCM WAV.
- **Compressed formats (MP3, AAC, etc.):** converted to the target format.
- **Already-converted files (`*_sp.wav`)** are skipped automatically, so a "mirror" folder is never re-converted.

## Requirements
- **Python 3.10+** - only needed to build or run from source
- **FFmpeg** on the system PATH - only needed to build or run from source
- (Recommended) The compiled `SP404Converter.exe`, which is **fully portable**: it bundles its own FFmpeg, so the end user needs **neither Python nor FFmpeg**

### Installing FFmpeg (Windows)
1. Download from https://ffmpeg.org/download.html (the "essentials" build from gyan.dev).
2. Extract it and add the `bin` folder to your system PATH.
3. Verify: open PowerShell and run `ffmpeg -version`

## Installation

### Quick start (Windows, one click)
Just run **`start.bat`** in the project folder. It creates a virtual environment,
installs the dependencies and launches the app. Works on the first and every later run.

### From source (as a Python package)
```bash
# Clone or download this project, then from its folder:

# Option A: install the deps only and run with main.py
pip install -r requirements.txt
python main.py

# Option B: full install (creates the `sp404-converter` command)
pip install .
sp404-converter
```

### Classic venv setup
```bash
# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
python main.py
```

## Usage
```bash
python main.py
```

Or just run the compiled `SP404Converter.exe` (see build instructions below).

### Interface
1. **Drag & drop** folders or audio files onto the window. The conversion queue groups the samples by their source folder, showing a folder header above each group.
2. (Optional) Choose an **output folder** - by default files are saved next to their source.
3. **"Preserve source folder structure"** is enabled by default:
   - With an output folder selected: the whole source folder is recreated inside the output folder - `output/<pack>/<subfolders>/...` - with the converted files in place (e.g. `Out/Boombap/Bass/kick_sp.wav`).
   - Without an output folder: a `<source>_sp` folder is created next to each source folder, mirroring its structure.
   - Disabled: every converted file is saved flat in the output folder.
4. Click **CONVERT ALL**.
5. Converted files get the `_sp.wav` suffix.

> **Note for Windows:** if the app is run as Administrator, Windows blocks dragging files from File Explorer (the forbidden cursor 🚫 is shown). Run it normally; the app warns you automatically if it detects elevated privileges.

## Building a standalone .exe
The build script bundles `ffmpeg.exe` and `ffprobe.exe` from your system into the executable, so the result is a single portable file.

```bash
pip install pyinstaller
python build_exe.py
```
The executable will be at `dist/SP404Converter.exe`.

> **Requirements for the build:** FFmpeg must be installed on the machine doing the build
> and available on its PATH (the build locates it with `shutil.which`). If FFmpeg is missing,
> the script warns you and produces an exe that is **not** portable.

### How the bundling works
- `converter.py` resolves the binaries with `sys._MEIPASS` when running inside the bundle (`ffmpeg_bin()` / `ffprobe_bin()`), and falls back to the system PATH when running from source (`python main.py`).
- `build_exe.py` passes `--add-binary "<path>\ffmpeg.exe;."` (and the same for `ffprobe.exe`) so both are extracted next to the app at runtime.
- Everything runs from a temporary folder that PyInstaller extracts at launch, so the `.exe` is the only file the user needs. No Python, no FFmpeg, no `styles.qss` required on the target machine.

### Custom icon
Drop a file named **`icon.ico`** in the project folder (any size; a multi-size 16-256 px icon is recommended). The build script detects it automatically:
- `--icon` sets it on the `.exe` file itself.
- It is bundled as a resource so the running window/taskbar shows it too.
Without `icon.ico` the build falls back to the default PyInstaller icon.

> **Note:** the one-file executable is large (~118 MB) because it includes Qt + FFmpeg.
> Some antivirus tools flag PyInstaller one-file builds; tell users it's a false positive
> or get a code-signing certificate for wider distribution.

## Supported input formats
`.wav`, `.mp3`, `.flac`, `.ogg`, `.m4a`, `.aac`, `.aiff`, `.aif`, `.wma`, `.opus`, `.webm`

## Project structure
```
sp404_converter/
 main.py            # Entry point
 gui.py             # Main window + drag & drop + queue grouping
 converter.py       # FFmpeg logic + SP-404 spec detection
 build_exe.py       # PyInstaller build script for the standalone .exe
 setup.py           # pip installation (creates the `sp404-converter` command)
 start.bat          # One-click first-run setup + launch (Windows)
 styles.qss         # Stylesheet (QSS/CSS)
 requirements.txt
 README.md
```

## Keyboard shortcuts
- `Delete` / `Supr` - Remove selected items from the queue
- `Ctrl+A` - Select all
- `Escape` - Clear the selection


