"""Shared fixtures: ffmpeg detection + tone generator with format control."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FFMPEG = shutil.which("ffmpeg")

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not on PATH")


def make_tone(
    path: Path,
    volume_db: float = 0.0,
    duration: float = 0.5,
    sample_rate: int | None = None,
    channels: int | None = None,
    codec: str = "pcm_s16le",
) -> Path:
    """Generate a short 440 Hz sine with controlled output format.

    `aevalsrc` produces a mono full-scale sine; `sample_rate`/`channels`/
    `codec` reshape it so tests can build compatible AND incompatible files.
    """
    assert FFMPEG is not None, "ffmpeg is required to generate test tones"
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FFMPEG, "-y",
        "-f", "lavfi", "-i",
        f"aevalsrc=sin(2*PI*440*t):s=44100:d={duration}",
    ]
    if volume_db:
        cmd += ["-af", f"volume={volume_db}dB"]
    if sample_rate:
        cmd += ["-ar", str(sample_rate)]
    if channels:
        cmd += ["-ac", str(channels)]
    cmd += ["-c:a", codec, str(path)]
    subprocess.run(cmd, capture_output=True, check=True, timeout=60)
    return path
