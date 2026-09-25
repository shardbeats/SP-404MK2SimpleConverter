"""Tests for the SP-404 spec table and ConversionResult defaults."""
from __future__ import annotations

from pathlib import Path

from converter import SP404_SPEC, ConversionResult


def test_spec_target_values():
    assert SP404_SPEC["recommended_sample_rate"] == 44100
    assert SP404_SPEC["channels"] == 2
    assert SP404_SPEC["bit_depth"] == 16
    assert SP404_SPEC["codec"] == "pcm_s16le"
    assert SP404_SPEC["format"] == "wav"


def test_spec_sample_rate_list():
    rates = SP404_SPEC["sample_rates"]
    for expected in (16000, 22050, 32000, 44100, 48000, 88200, 96000, 176400, 192000):
        assert expected in rates
    # Common non-pro-audio rates are rejected.
    assert 11025 not in rates
    assert 8000 not in rates


def test_result_defaults():
    result = ConversionResult(True, Path("kick.wav"))
    assert result.success is True
    assert result.input_path == Path("kick.wav")
    assert result.output_path is None
    assert result.error is None
