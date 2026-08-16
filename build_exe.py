#!/usr/bin/env python3
"""Build a standalone .exe for SP-404 MK2 Simple Converter using PyInstaller.

Bundles FFmpeg (ffmpeg.exe + ffprobe.exe) inside the executable so the result
is fully portable and doesn't need FFmpeg installed on the target machine.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "SP404Converter"
ICON_NAME = "icon.ico"


def find_ffmpeg() -> list[str]:
    """Locate ffmpeg.exe and ffprobe.exe on this machine."""
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        print("WARNING:")
        print("  ffmpeg/ffprobe not found on PATH, so the .exe will NOT be portable.")
        print("  Install FFmpeg first (https://ffmpeg.org/download.html) and add its bin/ to PATH.")
        return []
    return [ffmpeg, ffprobe]


def find_icon() -> Path:
    """Return the app icon (icon.ico) if present in the project folder."""
    icon = ROOT / ICON_NAME
    return icon if icon.exists() else None


def main():
    print("=" * 70)
    print(f"Building {APP_NAME}.exe (portable, with bundled FFmpeg) ...")
    print("=" * 70)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller not installed. Installing ...")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            check=True,
        )

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",
        "--windowed",
        "--name", APP_NAME,
        "--add-data", f"{ROOT / 'styles.qss'};.",
    ]

    for binary in find_ffmpeg():
        cmd.append("--add-binary")
        cmd.append(f"{binary};.")
        print(f"  Bundling: {binary}")

    icon = find_icon()
    if icon is not None:
        # --icon puts the custom icon on the .exe file itself; --add-data makes
        # it available at runtime (window/taskbar) via sys._MEIPASS.
        cmd.append("--icon")
        cmd.append(str(icon))
        cmd.append("--add-data")
        cmd.append(f"{icon};.")
        print(f"  Icon: {icon}")
    else:
        print("  WARNING: no icon.ico found in the project folder; using default PyInstaller icon.")

    cmd.append(str(ROOT / "main.py"))

    print("\nRunning:")
    print("  " + " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)

    exe = ROOT / "dist" / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print("=" * 70)
        print(f"BUILD OK: {exe}  ({size_mb:.1f} MB)")
    else:
        print("ERROR: compiled exe not found in dist/")
        sys.exit(1)


if __name__ == "__main__":
    main()