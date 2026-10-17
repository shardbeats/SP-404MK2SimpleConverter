"""Sampler Audio Converter - Conversion logic using ffmpeg.

Hardened against CPU / disk abuse:
- ffprobe/ffmpeg always run with timeouts
- ffmpeg is capped in threads and output duration
- oversized files / decompression bombs are rejected before conversion
- single ffprobe call per file (cached info, no process storms)
- partial outputs are cleaned up on failure / timeout / cancel
- directory scan is capped and never follows symlinks
"""

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable, Optional, Union
import json

# Hide ffmpeg/ffprobe console window on Windows (no visible cmd while converting).
NO_WINDOW_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

# --- Safety limits -----------------------------------------------------------
FFPROBE_TIMEOUT = 20      # s max per metadata probe (prevents hung workers)
FFMPEG_TIMEOUT = 300      # s max per file conversion (5 min, as before)
CHECK_TIMEOUT = 10        # s max for `ffmpeg -version` checks
MAX_FILE_BYTES = 250 * 1024 * 1024  # 250 MB input cap (decompression-bomb guard)
MAX_DURATION_SEC = 1800.0           # 30 min audio cap (prevents endless resampling)
MAX_FILES_PER_SCAN = 2000           # cap per folder scan
MAX_QUEUE_SIZE = 2000               # cap for the GUI queue
FFMPEG_THREADS = 2                  # cap ffmpeg CPU usage (x2 workers = bounded load)

CancelLike = Union[Event, Callable[[], bool], None]


def _is_cancelled(cancel_event: CancelLike) -> bool:
    """Accept threading.Event, callable, or None."""
    if cancel_event is None:
        return False
    try:
        if isinstance(cancel_event, Event):
            return cancel_event.is_set()
        if callable(cancel_event):
            return bool(cancel_event())
    except Exception:
        return False
    return False


@dataclass
class ConversionResult:
    success: bool
    input_path: Path
    output_path: Optional[Path] = None
    error: Optional[str] = None


# SP-404 MK2 compatible format specs
# Note: the MK2 works internally at 48 kHz / 16-bit (Roland: "The sample is
# converted to 48 kHz/16-bit when imported"), so 48000 is the default target.
TRAKK_SPEC = {
    "sample_rates": [16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000],
    "bit_depth": 16,
    "channels": 2,  # stereo
    "codec": "pcm_s16le",
    "format": "wav",
    "recommended_sample_rate": 48000,
}

# Alias de compatibilidad (ex SP404_SPEC → TRAKK_SPEC)
SP404_SPEC = TRAKK_SPEC

# Rates offered in the GUI selector. Kept to the two most useful ones:
# 48 kHz (native) and 44.1 kHz (legacy/DAW-friendly).
TARGET_SAMPLE_RATES = [48000, 44100]

# Extensions accepted anywhere (lowercase, with dot).
SUPPORTED_EXTENSIONS = {
    ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac",
    ".aiff", ".aif", ".wma", ".opus", ".webm",
}


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
    """Build ffmpeg command for SP-404 MK2 compatibility.

    Bounded: single audio stream, capped threads, capped output duration,
    never reads from stdin (so a crafted file can't block on a prompt).
    """
    try:
        target_rate = int(sample_rate) if sample_rate else int(TRAKK_SPEC["recommended_sample_rate"])
    except (TypeError, ValueError):
        target_rate = int(TRAKK_SPEC["recommended_sample_rate"])
    if target_rate not in TRAKK_SPEC["sample_rates"]:
        # Allow the two GUI targets plus spec rates; fall back otherwise
        # (prevents absurd -ar values from ever reaching ffmpeg).
        target_rate = int(TRAKK_SPEC["recommended_sample_rate"])
    return [
        ffmpeg_bin(),
        "-nostdin", "-hide_banner", "-loglevel", "error",
        "-y",  # overwrite output
        "-i", str(input_path),
        "-vn",  # ignore embedded video/cover art (saves CPU)
        "-ar", str(target_rate),
        "-ac", str(TRAKK_SPEC["channels"]),
        "-sample_fmt", "s16",  # 16-bit
        "-c:a", TRAKK_SPEC["codec"],
        "-threads", str(FFMPEG_THREADS),
        "-t", str(int(MAX_DURATION_SEC)),
        str(output_path),
    ]


def check_ffmpeg(timeout: int = CHECK_TIMEOUT) -> bool:
    """Verify ffmpeg is available (bundled or in PATH)."""
    try:
        subprocess.run([ffmpeg_bin(), "-version"], capture_output=True, check=True,
                       timeout=timeout, creationflags=NO_WINDOW_FLAGS)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired, OSError):
        return False
    except Exception:
        return False


def get_audio_info(file_path: Path, timeout: int = FFPROBE_TIMEOUT) -> dict:
    """Extract audio metadata using ffprobe (always bounded by timeout)."""
    try:
        p = Path(file_path)
        if not p.is_file():
            return {}
    except OSError:
        return {}
    cmd = [
        ffprobe_bin(), "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(file_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                timeout=timeout, creationflags=NO_WINDOW_FLAGS)
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

                try:
                    duration = float(stream.get("duration", 0) or 0)
                except (TypeError, ValueError):
                    duration = 0.0
                try:
                    sample_rate = int(stream.get("sample_rate", 0) or 0)
                except (TypeError, ValueError):
                    sample_rate = 0
                try:
                    channels = int(stream.get("channels", 0) or 0)
                except (TypeError, ValueError):
                    channels = 0

                return {
                    "sample_rate": sample_rate,
                    "channels": channels,
                    "codec": stream.get("codec_name", "unknown"),
                    "duration": duration,
                    "bit_depth": bit_depth,
                    "sample_fmt": sample_fmt,
                }
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError,
            FileNotFoundError, OSError):
        pass
    except Exception:
        pass
    return {}


def is_compatible_format(file_path: Path, info: Optional[dict] = None) -> bool:
    """Check if file already meets SP-404 MK2 specs.

    `info` may be a cached get_audio_info() dict to avoid a second probe.
    """
    if info is None:
        info = get_audio_info(file_path)
    if not info:
        return False  # Unknown format, needs conversion

    # Check sample rate compatibility
    sample_rate_ok = info.get("sample_rate") in TRAKK_SPEC["sample_rates"]

    # Check bit depth compatibility (16-bit or 24-bit)
    bit_depth_ok = info.get("bit_depth") in (16, 24)

    # Check channel compatibility (stereo preferred)
    channels_ok = info.get("channels") == TRAKK_SPEC["channels"] or info.get("channels") == 1

    # Check codec compatibility (PCM, not compressed)
    codec_ok = info.get("codec") in ("pcm_s16le", "pcm_s16be", "pcm_s24le", "pcm_s24be")

    return sample_rate_ok and bit_depth_ok and channels_ok and codec_ok


def needs_conversion(
    file_path: Path,
    target_sample_rate: Optional[int] = None,
    info: Optional[dict] = None,
) -> bool:
    """Check if file needs conversion.

    A file needs conversion when it is not SP-404 compatible at all, OR when
    it is compatible but its sample rate differs from the selected target
    ("force to rate" mode, so a whole pack ends up uniform).

    `info` is an optional cached get_audio_info() dict (single probe).
    """
    if info is None:
        info = get_audio_info(file_path)
    if not is_compatible_format(file_path, info=info):
        return True
    if target_sample_rate is not None:
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


def _cleanup_partial(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def convert_file(
    input_path: Path,
    output_dir: Path,
    source_root: Optional[Path] = None,
    preserve_structure: bool = False,
    target_sample_rate: Optional[int] = None,
    timeout: int = FFMPEG_TIMEOUT,
    cancel_event: CancelLike = None,
) -> ConversionResult:
    """Convert single file to SP-404 MK2 format (bounded + cancellable)."""
    if _is_cancelled(cancel_event):
        return ConversionResult(False, input_path, error="Cancelled")
    try:
        if not input_path.is_file():
            return ConversionResult(False, input_path, error="Input file not found")
    except OSError:
        return ConversionResult(False, input_path, error="Input file not found")

    # Size guard BEFORE any heavy work (decompression-bomb / disk-fill guard).
    try:
        if input_path.stat().st_size > MAX_FILE_BYTES:
            mb = MAX_FILE_BYTES // (1024 * 1024)
            return ConversionResult(False, input_path, error=f"File too large (>{mb} MB), skipped")
    except OSError as e:
        return ConversionResult(False, input_path, error=str(e))

    if target_sample_rate is None:
        target_sample_rate = int(TRAKK_SPEC["recommended_sample_rate"])
    try:
        target_sample_rate = int(target_sample_rate)
    except (TypeError, ValueError):
        target_sample_rate = int(TRAKK_SPEC["recommended_sample_rate"])

    # Determine output path
    try:
        output_path = compute_output_path(input_path, output_dir, source_root, preserve_structure)
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return ConversionResult(False, input_path, error=f"Cannot create output folder: {e}")

    if _is_cancelled(cancel_event):
        return ConversionResult(False, input_path, error="Cancelled")

    # Single metadata probe, reused for both checks below.
    info = get_audio_info(input_path)
    try:
        if float(info.get("duration", 0) or 0) > MAX_DURATION_SEC:
            return ConversionResult(False, input_path, error="Audio too long, skipped")
    except (TypeError, ValueError):
        pass

    # Skip if already at target (copy instead of convert)
    if not needs_conversion(input_path, target_sample_rate, info=info):
        try:
            shutil.copy2(input_path, output_path)
            return ConversionResult(True, input_path, output_path)
        except OSError as e:
            return ConversionResult(False, input_path, error=f"Copy failed: {e}")

    if _is_cancelled(cancel_event):
        return ConversionResult(False, input_path, error="Cancelled")

    # Run ffmpeg conversion (cancellable + bounded).
    cmd = build_ffmpeg_cmd(input_path, output_path, target_sample_rate)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=NO_WINDOW_FLAGS,
        )
    except FileNotFoundError:
        return ConversionResult(False, input_path, error="ffmpeg not found")
    except Exception as e:
        return ConversionResult(False, input_path, error=str(e))

    deadline = time.monotonic() + max(1, int(timeout))
    try:
        while True:
            try:
                returncode = proc.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                if _is_cancelled(cancel_event):
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    _cleanup_partial(output_path)
                    return ConversionResult(False, input_path, error="Cancelled")
                if time.monotonic() > deadline:
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except Exception:
                        pass
                    _cleanup_partial(output_path)
                    return ConversionResult(False, input_path, error="Conversion timeout")
                continue
        try:
            _, stderr = proc.communicate(timeout=5)
        except Exception:
            stderr = ""
        if returncode == 0 and output_path.exists():
            return ConversionResult(True, input_path, output_path)
        _cleanup_partial(output_path)
        err = (stderr or "").strip().splitlines()
        err = err[-1][:500] if err else "Unknown ffmpeg error"
        return ConversionResult(False, input_path, error=err)
    except Exception as e:
        try:
            proc.kill()
        except Exception:
            pass
        _cleanup_partial(output_path)
        return ConversionResult(False, input_path, error=str(e))


def find_audio_files(
    folder: Path, recursive: bool = True, max_files: int = MAX_FILES_PER_SCAN
) -> list[Path]:
    """Find all supported audio files in folder.

    Bounded (max_files), never follows symlinks (loop/junction guard),
    single-pass case-insensitive extension check.
    """
    try:
        base = Path(folder)
        if not base.is_dir():
            return []
    except OSError:
        return []
    try:
        if base.is_symlink():
            return []
    except OSError:
        return []

    files: list[Path] = []
    try:
        if not recursive:
            try:
                with os.scandir(base) as it:
                    for entry in it:
                        if len(files) >= max_files:
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            if Path(entry.name).suffix.lower() in SUPPORTED_EXTENSIONS:
                                files.append(Path(entry.path))
                        except OSError:
                            continue
            except OSError:
                return []
            return sorted(set(files))

        base_str = str(base)
        for root, dirs, filenames in os.walk(base_str, topdown=True, followlinks=False):
            # Never descend into symlinked dirs (junction/loop guard) + depth cap.
            try:
                root_depth = len(Path(root).relative_to(base).parts)
            except ValueError:
                root_depth = 0
            if root_depth > 25:
                dirs[:] = []
                continue
            dirs[:] = [d for d in dirs
                       if not (Path(root, d).is_symlink()) and not d.startswith("$")]
            for name in filenames:
                if len(files) >= max_files:
                    return sorted(set(files))
                if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                full = Path(root) / name
                try:
                    if full.is_symlink():
                        continue
                except OSError:
                    continue
                files.append(full)
    except OSError:
        pass
    return sorted(set(files))
