"""Tests for ffprobe metadata extraction."""
from __future__ import annotations

from pathlib import Path

from converter import get_audio_info

from .conftest import make_tone, needs_ffmpeg


@needs_ffmpeg
def test_get_audio_info_of_generated_wav(tmp_path: Path):
    tone = make_tone(tmp_path / "tone.wav", sample_rate=44100, channels=2)
    info = get_audio_info(tone)
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
    assert info["codec"] == "pcm_s16le"
    assert info["bit_depth"] == 16
    assert info["sample_fmt"] == "s16"
    assert info["duration"] > 0


@needs_ffmpeg
def test_get_audio_info_reports_24bit(tmp_path: Path):
    tone = make_tone(tmp_path / "tone24.wav", codec="pcm_s24le")
    info = get_audio_info(tone)
    assert info["bit_depth"] == 24


@needs_ffmpeg
def test_get_audio_info_of_mp3(tmp_path: Path):
    tone = make_tone(tmp_path / "tone.mp3", codec="mp3")
    info = get_audio_info(tone)
    assert info["codec"] == "mp3"
    assert info["sample_rate"] > 0


def test_get_audio_info_missing_returns_empty(tmp_path: Path):
    assert get_audio_info(tmp_path / "nope.wav") == {}


def test_get_audio_info_non_audio_returns_empty(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text("hello")
    assert get_audio_info(text) == {}
