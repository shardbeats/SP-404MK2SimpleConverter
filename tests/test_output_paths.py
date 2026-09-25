"""Tests for output-path computation (no ffmpeg needed)."""
from __future__ import annotations

from pathlib import Path

from converter import compute_output_path


def test_flat_output_with_wav_suffix(tmp_path: Path):
    src = tmp_path / "pack" / "kick.wav"
    assert compute_output_path(src, tmp_path / "out") == tmp_path / "out" / "kick_sp.wav"


def test_non_wav_input_becomes_wav(tmp_path: Path):
    src = tmp_path / "song.mp3"
    assert compute_output_path(src, tmp_path / "out") == tmp_path / "out" / "song_sp.wav"


def test_uppercase_extension_normalized(tmp_path: Path):
    src = tmp_path / "LOOP.WAV"
    assert compute_output_path(src, tmp_path / "out") == tmp_path / "out" / "LOOP_sp.wav"


def test_preserve_structure_mirrors_subfolders(tmp_path: Path):
    root = tmp_path / "Boombap"
    src = root / "Bass" / "kick.mp3"
    out = tmp_path / "Out"
    assert compute_output_path(src, out, source_root=root, preserve_structure=True) == \
        out / "Bass" / "kick_sp.wav"


def test_preserve_structure_without_root_is_flat(tmp_path: Path):
    src = tmp_path / "kick.wav"
    assert compute_output_path(src, tmp_path / "out", preserve_structure=True) == \
        tmp_path / "out" / "kick_sp.wav"


def test_file_outside_root_falls_back_to_flat(tmp_path: Path):
    root = tmp_path / "pack"
    elsewhere = tmp_path / "other" / "snare.wav"
    assert compute_output_path(elsewhere, tmp_path / "out",
                               source_root=root, preserve_structure=True) == \
        tmp_path / "out" / "snare_sp.wav"
