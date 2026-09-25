"""Tests for audio file discovery (no ffmpeg needed)."""
from __future__ import annotations

from pathlib import Path

from converter import find_audio_files


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def test_finds_supported_recursively(tmp_path: Path):
    _touch(tmp_path / "kick.wav")
    _touch(tmp_path / "kit" / "snare.mp3")
    _touch(tmp_path / "kit" / "deep" / "hat.flac")
    found = find_audio_files(tmp_path)
    assert len(found) == 3
    assert found == sorted(found)


def test_uppercase_extensions_found(tmp_path: Path):
    _touch(tmp_path / "KICK.WAV")
    _touch(tmp_path / "song.MP3")
    assert len(find_audio_files(tmp_path)) == 2


def test_unsupported_ignored(tmp_path: Path):
    _touch(tmp_path / "notes.txt")
    _touch(tmp_path / "cover.jpg")
    _touch(tmp_path / "kick.wav")
    assert find_audio_files(tmp_path) == [tmp_path / "kick.wav"]


def test_non_recursive_only_top_level(tmp_path: Path):
    _touch(tmp_path / "top.wav")
    _touch(tmp_path / "sub" / "nested.wav")
    assert find_audio_files(tmp_path, recursive=False) == [tmp_path / "top.wav"]


def test_empty_folder(tmp_path: Path):
    assert find_audio_files(tmp_path) == []
