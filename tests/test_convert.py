"""End-to-end convert_file tests with generated tones (real ffmpeg)."""
from __future__ import annotations

from pathlib import Path

from converter import convert_file, get_audio_info, is_compatible_format

from .conftest import make_tone, needs_ffmpeg


def test_missing_input_fails(tmp_path: Path):
    result = convert_file(tmp_path / "ghost.wav", tmp_path / "out")
    assert result.success is False
    assert "not found" in (result.error or "").lower()


@needs_ffmpeg
def test_compatible_file_is_copied_not_reencoded(tmp_path: Path):
    src = make_tone(tmp_path / "ok.wav", sample_rate=48000, channels=2)
    out = tmp_path / "out"
    result = convert_file(src, out)
    assert result.success is True
    assert result.output_path == out / "ok_sp.wav"
    assert result.output_path.exists()
    assert result.output_path.read_bytes() == src.read_bytes()
    assert is_compatible_format(result.output_path) is True


@needs_ffmpeg
def test_unsupported_rate_gets_converted_to_spec(tmp_path: Path):
    src = make_tone(tmp_path / "lo.wav", sample_rate=11025, channels=2)
    result = convert_file(src, tmp_path / "out")
    assert result.success is True
    assert result.output_path is not None and result.output_path.suffix == ".wav"
    info = get_audio_info(result.output_path)
    assert info["sample_rate"] == 48000
    assert info["channels"] == 2
    assert info["codec"] == "pcm_s16le"
    assert info["bit_depth"] == 16


@needs_ffmpeg
def test_explicit_44100_target_is_honored(tmp_path: Path):
    src = make_tone(tmp_path / "lo.wav", sample_rate=11025, channels=2)
    result = convert_file(src, tmp_path / "out", target_sample_rate=44100)
    assert result.success is True
    assert get_audio_info(result.output_path)["sample_rate"] == 44100


@needs_ffmpeg
def test_compatible_rate_mismatch_gets_resampled(tmp_path: Path):
    # "Force to rate": a compatible 44.1 kHz file with target 48 kHz
    # must be resampled, not copied.
    from converter import needs_conversion

    src = make_tone(tmp_path / "ok44.wav", sample_rate=44100, channels=2)
    assert needs_conversion(src, 48000) is True
    assert needs_conversion(src, 44100) is False
    result = convert_file(src, tmp_path / "out", target_sample_rate=48000)
    assert result.success is True
    assert result.output_path.read_bytes() != src.read_bytes()
    assert get_audio_info(result.output_path)["sample_rate"] == 48000


@needs_ffmpeg
def test_mp3_gets_converted_to_wav(tmp_path: Path):
    src = make_tone(tmp_path / "song.mp3", codec="mp3")
    result = convert_file(src, tmp_path / "out")
    assert result.success is True
    assert result.output_path == tmp_path / "out" / "song_sp.wav"
    assert is_compatible_format(result.output_path) is True


@needs_ffmpeg
def test_preserve_structure_end_to_end(tmp_path: Path):
    root = tmp_path / "Boombap"
    src = make_tone(root / "Bass" / "kick.mp3", codec="mp3")
    out = tmp_path / "Out"
    result = convert_file(src, out, source_root=root, preserve_structure=True)
    assert result.success is True
    assert result.output_path == out / "Bass" / "kick_sp.wav"
    assert result.output_path.exists()


@needs_ffmpeg
def test_compatible_24bit_file_is_copied_not_reencoded(tmp_path: Path):
    # Regression: 24-bit PCM must be detected as compatible (ffprobe reports
    # sample_fmt s32 with bits_per_sample 24) and copied as-is.
    src = make_tone(tmp_path / "t24.wav", sample_rate=48000, channels=2, codec="pcm_s24le")
    result = convert_file(src, tmp_path / "out")
    assert result.success is True
    assert result.output_path.read_bytes() == src.read_bytes()
    assert get_audio_info(result.output_path)["bit_depth"] == 24


@needs_ffmpeg
def test_mono_8bit_gets_converted(tmp_path: Path):
    src = make_tone(tmp_path / "tiny.wav", sample_rate=44100, codec="pcm_u8")
    result = convert_file(src, tmp_path / "out")
    assert result.success is True
    assert is_compatible_format(result.output_path) is True
