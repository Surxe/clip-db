"""Sizing math for the share compressor: the video-bitrate budget and the resolution
ladder. Pure functions, so no ffmpeg is invoked."""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_compress():
    spec = importlib.util.spec_from_file_location("compress_mod", REPO_ROOT / "clip-distributor" / "compress.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclass + future-annotations needs the module registered
    spec.loader.exec_module(mod)
    return mod


compress = _load_compress()
CAP = compress.DISCORD_UNBOOSTED_CAP  # 10 MiB


def test_budget_shrinks_with_duration():
    # Longer clip -> smaller per-second budget.
    short = compress.video_budget_kbps(10, CAP, headroom=0.90, audio_kbps=96)
    long = compress.video_budget_kbps(30, CAP, headroom=0.90, audio_kbps=96)
    assert short > long > 0


def test_budget_fits_under_cap():
    # A clip encoded at the budgeted bitrate (+ audio) must fit the headroom target.
    dur, headroom, audio = 30.0, 0.90, 96
    v = compress.video_budget_kbps(dur, CAP, headroom, audio)
    encoded_bytes = (v + audio) * 1000 * dur / 8
    assert encoded_bytes <= CAP * headroom + 1  # +1 for the int() truncation


def test_budget_reserves_audio():
    v_lo = compress.video_budget_kbps(30, CAP, 0.90, audio_kbps=64)
    v_hi = compress.video_budget_kbps(30, CAP, 0.90, audio_kbps=192)
    assert v_lo - v_hi == pytest.approx(192 - 64, abs=1)


@pytest.mark.parametrize("kbps,expected", [(4000, 720), (2500, 720), (2000, 540), (1200, 540), (800, 480)])
def test_ladder_steps_down(kbps, expected):
    assert compress.pick_height(kbps, src_h=720) == expected


def test_ladder_never_upscales():
    # A 540p source stays 540p even when the budget could afford 720p.
    assert compress.pick_height(4000, src_h=540) == 540
