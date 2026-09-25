"""Tests for binary resolution and the ffmpeg command builder."""
from __future__ import annotations

import sys
from pathlib import Path

import converter
from converter import (
    SP404_SPEC,
    build_ffmpeg_cmd,
    check_ffmpeg,
    ffmpeg_bin,
    ffprobe_bin,
)

from .conftest import needs_ffmpeg


def test_bins_fall_back_to_path(monkeypatch):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert ffmpeg_bin() == "ffmpeg"
    assert ffprobe_bin() == "ffprobe"


def test_bins_use_bundled_when_present(tmp_path: Path, monkeypatch):
    bundled = tmp_path / "ffmpeg.exe"
    bundled.write_bytes(b"x")
    (tmp_path / "ffprobe.exe").write_bytes(b"x")
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ffmpeg_bin() == str(bundled)
    assert ffprobe_bin() == str(tmp_path / "ffprobe.exe")


def test_bins_ignore_empty_bundle_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert ffmpeg_bin() == "ffmpeg"


def test_check_ffmpeg_false_when_binary_missing(monkeypatch):
    monkeypatch.setattr(converter, "ffmpeg_bin", lambda: "definitely-not-a-real-binary")
    assert check_ffmpeg() is False


@needs_ffmpeg
def test_check_ffmpeg_true_with_real_binary():
    assert check_ffmpeg() is True


def test_build_ffmpeg_cmd_targets_sp404_spec(tmp_path: Path):
    src = tmp_path / "kick.mp3"
    dst = tmp_path / "kick_sp.wav"
    cmd = build_ffmpeg_cmd(src, dst)
    assert cmd[0] == ffmpeg_bin()
    assert "-y" in cmd
    assert cmd[cmd.index("-i") + 1] == str(src)
    assert cmd[cmd.index("-ar") + 1] == str(SP404_SPEC["recommended_sample_rate"])
    assert cmd[cmd.index("-ac") + 1] == str(SP404_SPEC["channels"])
    assert cmd[cmd.index("-sample_fmt") + 1] == "s16"
    assert cmd[cmd.index("-c:a") + 1] == SP404_SPEC["codec"]
    assert cmd[-1] == str(dst)
    # Pure linear conversion: no volume/compression filters.
    assert "-af" not in cmd
