#!/usr/bin/env python3
"""Size-targeted share compressor.

Transcode a (merged, single-audio) clip master down to fit under a byte cap so it
can be uploaded *inline* to a Discord channel. Standalone CLI + importable API.

Design (see docs): pick a video bitrate from the size budget and duration, then step
the resolution DOWN a ladder if that bitrate would be too low to hold the current
resolution cleanly. H.264 + AAC in MP4 with +faststart, because inline Discord
playback is only reliable for H.264.

Intended wiring: run this AFTER the audio-merge step (clip_core.media.regenerate_merged),
feeding it the *_merged.mp4:

    from compress import compress_for_share
    result = compress_for_share(merged_path, out_path)

Video dims come from a local ffprobe (clip_core.media.probe_duration is format-only);
everything else is dependency-light.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import tempfile
from pathlib import Path

# Webhook upload cap on an UNBOOSTED server (10 MiB). Discord reports these in MiB
# and changes them; keep it a parameter, never a hard-coded literal at call sites.
DISCORD_UNBOOSTED_CAP = 10 * 1024 * 1024


@dataclasses.dataclass
class CompressResult:
    src: Path
    dst: Path
    duration: float
    src_size: int
    out_size: int
    cap_bytes: int
    target_bytes: int
    src_height: int
    out_height: int
    out_fps: float
    video_kbps: int
    audio_kbps: int

    @property
    def under_cap(self) -> bool:
        # Fit == under the REAL upload cap; target_bytes is only the encode aim.
        return self.out_size <= self.cap_bytes

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["src"] = str(self.src)
        d["dst"] = str(self.dst)
        d["under_cap"] = self.under_cap
        d["ratio"] = round(self.src_size / self.out_size, 2) if self.out_size else None
        return d


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, text=True)


def probe_video(src: Path) -> tuple[int, int, float, float]:
    """Return (width, height, fps, duration_seconds) for the first video stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate",
        "-show_entries", "format=duration",
        "-of", "json", str(src),
    ]
    data = json.loads(_run(cmd).stdout)
    st = data["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    fps = float(num) / float(den) if float(den) else 0.0
    return int(st["width"]), int(st["height"]), fps, float(data["format"]["duration"])


def video_budget_kbps(duration: float, cap_bytes: int, headroom: float, audio_kbps: int) -> int:
    """Average video bitrate (kbps) that lands a `duration`-second clip under the cap.

    Pure function (no I/O) so the sizing math is unit-testable. Reserves `audio_kbps`
    for the mixed track and keeps `headroom` fraction of the cap as muxing/estimation
    margin. May return a value below any usable floor -- the caller decides.
    """
    target_bytes = int(cap_bytes * headroom)
    total_kbps = (target_bytes * 8 / duration) / 1000.0
    return int(total_kbps - audio_kbps)


def pick_height(video_kbps: int, src_h: int) -> int:
    """Resolution ladder: only step DOWN, and never upscale past the source.

    Thresholds are the bitrate at which each resolution stops looking clean for
    fast-motion gameplay in H.264 (see docs table).
    """
    if video_kbps >= 2500:
        target = 720
    elif video_kbps >= 1200:
        target = 540
    else:
        target = 480
    return min(target, src_h)


def compress_for_share(
    src,
    dst,
    *,
    cap_bytes: int = DISCORD_UNBOOSTED_CAP,
    headroom: float = 0.90,
    audio_kbps: int = 96,
    min_video_kbps: int = 350,
    preset: str = "slow",
    fps_cap: float = 30.0,
    long_clip_fps: float = 24.0,
    long_clip_seconds: float = 45.0,
) -> CompressResult:
    """Transcode `src` to `dst` so the result fits under `cap_bytes`.

    Two-pass libx264 targeting an average bitrate derived from the size budget, so
    the output lands close to (just under) the cap. Raises ValueError if the clip is
    too long to fit at a usable quality floor.
    """
    src = Path(src)
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    src_size = src.stat().st_size
    w, h, fps, dur = probe_video(src)

    video_kbps = video_budget_kbps(dur, cap_bytes, headroom, audio_kbps)
    if video_kbps < min_video_kbps:
        raise ValueError(
            f"{src.name}: {dur:.0f}s won't fit {cap_bytes} bytes at usable quality "
            f"(video budget {video_kbps} kbps < floor {min_video_kbps} kbps). "
            f"Trim the clip or raise the cap (boosted server)."
        )

    out_h = pick_height(video_kbps, h)
    out_fps = long_clip_fps if dur > long_clip_seconds else min(fps_cap, fps)
    # scale=-2 keeps aspect and forces even dims (required by yuv420p/H.264).
    vf = f"scale=-2:{out_h}:flags=lanczos,fps={out_fps:g}"

    with tempfile.TemporaryDirectory(prefix="x264pass_") as td:
        passlog = str(Path(td) / "ffpass")
        common = [
            "ffmpeg", "-hide_banner", "-y",
            "-i", str(src),
            "-c:v", "libx264", "-preset", preset,
            "-b:v", f"{video_kbps}k",
            "-pix_fmt", "yuv420p",
            "-vf", vf,
        ]
        # Pass 1: analyse, no audio, discard output.
        _run(common + ["-pass", "1", "-passlogfile", passlog, "-an", "-f", "mp4", "/dev/null"])
        # Pass 2: real encode with mixed audio + faststart for inline playback.
        _run(common + [
            "-pass", "2", "-passlogfile", passlog,
            "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-ac", "2",
            "-movflags", "+faststart",
            str(dst),
        ])

    return CompressResult(
        src=src, dst=dst, duration=dur,
        src_size=src_size, out_size=dst.stat().st_size,
        cap_bytes=cap_bytes, target_bytes=int(cap_bytes * headroom),
        src_height=h, out_height=out_h, out_fps=out_fps,
        video_kbps=video_kbps, audio_kbps=audio_kbps,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", help="input clip (a merged master)")
    ap.add_argument("dst", help="output mp4 path")
    ap.add_argument("--cap-bytes", type=int, default=DISCORD_UNBOOSTED_CAP,
                    help="upload cap in bytes (default 10 MiB, unboosted server)")
    ap.add_argument("--headroom", type=float, default=0.90, help="fraction of cap to target")
    ap.add_argument("--audio-kbps", type=int, default=96)
    ap.add_argument("--preset", default="slow")
    args = ap.parse_args()

    result = compress_for_share(
        args.src, args.dst,
        cap_bytes=args.cap_bytes, headroom=args.headroom,
        audio_kbps=args.audio_kbps, preset=args.preset,
    )
    print(json.dumps(result.as_dict(), indent=2))


if __name__ == "__main__":
    main()
