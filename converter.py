"""Sampler Audio Converter - Conversion logic using ffmpeg."""

import subprocess
import shlex
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
import json

# Hide ffmpeg/ffprobe console window on Windows (no visible cmd while converting).
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


@dataclass
class ConversionResult:
    success: bool
    input_path: Path
    output_path: Optional[Path] = None
    error: Optional[str] = None


# SP-404 MK2 compatible format specs
# Note: the MK2 works internally at 48 kHz / 16-bit (Roland: "The sample is
# converted to 48 kHz/16-bit when imported"), so 48000 is the default target.
SP404_SPEC = {
    "sample_rates": [16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000],
    "bit_depth": 16,
    "channels": 2,  # stereo
    "codec": "pcm_s16le",
    "format": "wav",
    "recommended_sample_rate": 48000,
}

# Rates offered in the GUI selector. Kept to the two most useful ones:
# 48 kHz (native) and 44.1 kHz (legacy/DAW-friendly).
TARGET_SAMPLE_RATES = [48000, 44100]


def ffmpeg_bin() -> str:
    """Path to the ffmpeg binary.

    In a PyInstaller build the binaries are bundled via --add-binary and
    extracted next to the app (sys._MEIPASS); otherwise fall back to PATH.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "ffmpeg.exe"
        if candidate.exists():
            return str(candidate)
    return "ffmpeg"


def ffprobe_bin() -> str:
    """Path to the ffprobe binary (same logic as ffmpeg_bin)."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "ffprobe.exe"
        if candidate.exists():
            return str(candidate)
    return "ffprobe"


def build_ffmpeg_cmd(
    input_path: Path, output_path: Path, sample_rate: Optional[int] = None
) -> list[str]:
    """Build ffmpeg command for SP-404 MK2 compatibility."""
    target_rate = sample_rate or SP404_SPEC["recommended_sample_rate"]
    return [
        ffmpeg_bin(), "-y",  # overwrite output
        "-i", str(input_path),
        "-ar", str(target_rate),
        "-ac", str(SP404_SPEC["channels"]),
        "-sample_fmt", "s16",  # 16-bit
        "-c:a", SP404_SPEC["codec"],
        str(output_path),
    ]


def check_ffmpeg() -> bool:
    """Verify ffmpeg is available (bundled or in PATH)."""
    try:
        subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, check=True,
                       creationflags=NO_WINDOW_FLAGS)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_audio_info(file_path: Path) -> dict:
    """Extract audio metadata using ffprobe."""
    cmd = [
        ffprobe_bin(), "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=NO_WINDOW_FLAGS)
        data = json.loads(result.stdout)
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "audio":
                sample_fmt = stream.get("sample_fmt", "")
                # Prefer the real bit depth when ffprobe reports it: for
                # 24-bit PCM ffprobe decodes into s32 containers, so
                # sample_fmt alone ("s32") would misdetect 24-bit as 32-bit.
                bit_depth = stream.get("bits_per_sample") or stream.get("bits_per_raw_sample")
                try:
                    bit_depth = int(bit_depth) if bit_depth else None
                except (TypeError, ValueError):
                    bit_depth = None
                if bit_depth not in (8, 16, 24, 32):
                    bit_depth = 16 if "s16" in sample_fmt else "unknown"
                    if "s24" in sample_fmt:
                        bit_depth = 24
                    if "s32" in sample_fmt:
                        bit_depth = 32

                return {
                    "sample_rate": int(stream.get("sample_rate", 0)),
                    "channels": int(stream.get("channels", 0)),
                    "codec": stream.get("codec_name", "unknown"),
                    "duration": float(stream.get("duration", 0)),
                    "bit_depth": bit_depth,
                    "sample_fmt": sample_fmt,
                }
    except Exception:
        pass
    return {}


def is_compatible_format(file_path: Path) -> bool:
    """Check if file already meets SP-404 MK2 specs."""
    info = get_audio_info(file_path)
    if not info:
        return False  # Unknown format, needs conversion

    # Check sample rate compatibility
    sample_rate_ok = info.get("sample_rate") in SP404_SPEC["sample_rates"]

    # Check bit depth compatibility (16-bit or 24-bit)
    bit_depth_ok = info.get("bit_depth") in (16, 24)

    # Check channel compatibility (stereo preferred)
    channels_ok = info.get("channels") == SP404_SPEC["channels"] or info.get("channels") == 1

    # Check codec compatibility (PCM, not compressed)
    codec_ok = info.get("codec") in ("pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be")

    return sample_rate_ok and bit_depth_ok and channels_ok and codec_ok


def needs_conversion(file_path: Path, target_sample_rate: Optional[int] = None) -> bool:
    """Check if file needs conversion.

    A file needs conversion when it is not SP-404 compatible at all, OR when
    it is compatible but its sample rate differs from the selected target
    ("force to rate" mode, so a whole pack ends up uniform).
    """
    if not is_compatible_format(file_path):
        return True
    if target_sample_rate is not None:
        info = get_audio_info(file_path)
        try:
            if int(info.get("sample_rate", 0)) != int(target_sample_rate):
                return True
        except (TypeError, ValueError):
            return True
    return False


def compute_output_path(
    input_path: Path,
    output_dir: Path,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
) -> Path:
    """Compute the final output path for the converted file.

    When preserve_structure is True and a source_root is known, the relative
    folder structure of the source file (inside source_root) is kept within
    output_dir, preserving the original layout as a mirror folder.
    """
    rel = Path(".")
    if preserve_structure and source_root is not None:
        try:
            rel = input_path.parent.relative_to(source_root)
        except ValueError:
            rel = Path(".")

    output_path = output_dir / rel / f"{input_path.stem}_sp{input_path.suffix.lower()}"
    if output_path.suffix.lower() != ".wav":
        output_path = output_path.with_suffix(".wav")
    return output_path


def convert_file(
    input_path: Path,
    output_dir: Path,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
    target_sample_rate: Optional[int] = None,
) -> ConversionResult:
    """Convert single file to SP-404 MK2 format."""
    if not input_path.exists():
        return ConversionResult(False, input_path, error="Input file not found")

    if target_sample_rate is None:
        target_sample_rate = int(SP404_SPEC["recommended_sample_rate"])

    # Determine output path
    output_path = compute_output_path(input_path, output_dir, source_root, preserve_structure)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Skip if already at target (copy instead of convert)
    if not needs_conversion(input_path, target_sample_rate):
        # Copy instead of convert
        import shutil
        shutil.copy2(input_path, output_path)
        return ConversionResult(True, input_path, output_path)

    # Run ffmpeg conversion
    cmd = build_ffmpeg_cmd(input_path, output_path, target_sample_rate)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min max per file
            creationflags=NO_WINDOW_FLAGS,
        )
        if result.returncode == 0 and output_path.exists():
            return ConversionResult(True, input_path, output_path)
        else:
            return ConversionResult(
                False, input_path, error=result.stderr or "Unknown ffmpeg error"
            )
    except subprocess.TimeoutExpired:
        return ConversionResult(False, input_path, error="Conversion timeout")
    except Exception as e:
        return ConversionResult(False, input_path, error=str(e))


def find_audio_files(folder: Path, recursive: bool = True) -> list[Path]:
    """Find all supported audio files in folder."""
    audio_extensions = {
        ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
        ".aiff", ".aif", ".wma", ".opus", ".webm",
    }
    pattern = "**/*" if recursive else "*"
    files = []
    for ext in audio_extensions:
        files.extend(folder.glob(f"{pattern}{ext}"))
        files.extend(folder.glob(f"{pattern}{ext.upper()}"))
    return sorted(set(files))