"""Tests for SP-404 compatibility detection, one case per rule."""
from __future__ import annotations

from pathlib import Path

from converter import is_compatible_format, needs_conversion

from .conftest import make_tone, needs_ffmpeg


@needs_ffmpeg
def test_compatible_stereo_16bit_wav(tmp_path: Path):
    tone = make_tone(tmp_path / "ok.wav", sample_rate=44100, channels=2)
    assert is_compatible_format(tone) is True
    assert needs_conversion(tone) is False


@needs_ffmpeg
def test_compatible_mono_counts_as_compatible(tmp_path: Path):
    tone = make_tone(tmp_path / "mono.wav", sample_rate=48000)  # aevalsrc is mono
    assert is_compatible_format(tone) is True


@needs_ffmpeg
def test_compatible_24bit_counts_as_compatible(tmp_path: Path):
    tone = make_tone(tmp_path / "t24.wav", sample_rate=44100, channels=2, codec="pcm_s24le")
    assert is_compatible_format(tone) is True


@needs_ffmpeg
def test_bad_sample_rate_needs_conversion(tmp_path: Path):
    tone = make_tone(tmp_path / "lo.wav", sample_rate=11025, channels=2)
    assert needs_conversion(tone) is True


@needs_ffmpeg
def test_bad_bit_depth_needs_conversion(tmp_path: Path):
    tone = make_tone(tmp_path / "t32.wav", sample_rate=44100, channels=2, codec="pcm_s32le")
    assert needs_conversion(tone) is True


@needs_ffmpeg
def test_bad_channel_count_needs_conversion(tmp_path: Path):
    tone = make_tone(tmp_path / "surround.wav", sample_rate=44100, channels=6)
    assert needs_conversion(tone) is True


@needs_ffmpeg
def test_compressed_codec_needs_conversion(tmp_path: Path):
    tone = make_tone(tmp_path / "song.mp3", codec="mp3")
    assert needs_conversion(tone) is True


@needs_ffmpeg
def test_lossy_8bit_pcm_needs_conversion(tmp_path: Path):
    tone = make_tone(tmp_path / "tiny.wav", sample_rate=44100, codec="pcm_u8")
    assert needs_conversion(tone) is True


def test_missing_file_needs_conversion(tmp_path: Path):
    assert is_compatible_format(tmp_path / "ghost.wav") is False
    assert needs_conversion(tmp_path / "ghost.wav") is True
