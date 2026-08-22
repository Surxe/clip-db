"""Media I/O: master/merged detection, ffprobe metadata, intake move, merge regeneration."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

MERGED_SUFFIX = "_merged"


def is_merged(path) -> bool:
    return Path(path).stem.endswith(MERGED_SUFFIX)


def is_master(path) -> bool:
    p = Path(path)
    return p.suffix.lower() == ".mp4" and not is_merged(p)


def stem_of(path) -> str:
    """Asset stem — strips the _merged suffix so a master and its merged file share an id."""
    s = Path(path).stem
    return s[: -len(MERGED_SUFFIX)] if s.endswith(MERGED_SUFFIX) else s


def merged_name_for(master_path) -> str:
    p = Path(master_path)
    return f"{p.stem}{MERGED_SUFFIX}{p.suffix}"


def iter_masters(intake_dir):
    """Yield master clips (`*.mp4` excluding `*_merged.mp4`) from a directory."""
    for p in sorted(Path(intake_dir).glob("*.mp4")):
        if is_master(p):
            yield p


def probe_duration(path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def date_from_stem(stem: str) -> str | None:
    """Pull a YYYY-MM-DD out of a timestamped stem (e.g. 2026-07-30_22-03-03)."""
    m = _DATE_RE.match(stem)
    return m.group(1) if m else None


def probe_creation_date(path) -> str | None:
    """The container's creation_time tag as YYYY-MM-DD, if the recorder embedded one.

    Probe the master (a merged/edited re-encode usually strips this tag).
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format_tags=creation_time",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        return None
    m = _DATE_RE.match(out)
    return m.group(1) if m else None


def file_mtime_date(path) -> str | None:
    """The file's modification time as YYYY-MM-DD (local time)."""
    try:
        ts = Path(path).stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def resolve_date(master_path, stem: str) -> str | None:
    """Best-effort clip date, most-trustworthy source first: an explicit timestamp
    in the stem, then the container creation_time tag, then the file mtime. Returns
    None only if none apply (never falls back to the ingest/processing date)."""
    return (
        date_from_stem(stem)
        or probe_creation_date(master_path)
        or file_mtime_date(master_path)
    )


def move_into_library(src, library_dir) -> Path:
    """Move a clip out of the (NTFS) staging dir into the library. Cross-fs = copy+delete."""
    library = Path(library_dir)
    library.mkdir(parents=True, exist_ok=True)
    dst = library / Path(src).name
    shutil.move(str(src), str(dst))
    return dst


def _count_audio_streams(path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=index", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return len(json.loads(out).get("streams", []))


def regenerate_merged(master_path, out_path=None) -> Path:
    """Rebuild the merged (mixed-audio) rendition from a split-audio master via ffmpeg.

    Port of the old merge_tracks.py, generalized to any audio-track count and without
    the Windows-only clipboard step.
    """
    master = Path(master_path)
    out = Path(out_path) if out_path else master.with_name(merged_name_for(master))
    n = _count_audio_streams(master)
    if n <= 1:
        # Nothing to mix -- straight remux. `+faststart` still relocates the moov
        # atom to the front so the merged file streams in a web player like the master.
        cmd = ["ffmpeg", "-y", "-i", str(master), "-c", "copy",
               "-movflags", "+faststart", str(out)]
    else:
        inputs = "".join(f"[0:a:{i}]" for i in range(n))
        # normalize=0: amix otherwise scales each input by 1/n, so the mix comes out
        # quieter than any single track (game audio ~inaudible). Sum at full level and
        # brick-wall with alimiter so summed peaks can't clip. +faststart puts the moov
        # atom up front -- without it ffmpeg writes moov at the end and streaming players
        # render the merged clip wrong (blank / unseekable) even though the master is fine.
        cmd = [
            "ffmpeg", "-y", "-i", str(master),
            "-filter_complex",
            f"{inputs}amix=inputs={n}:duration=longest:normalize=0,alimiter=limit=0.95[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", str(out),
        ]
    subprocess.run(cmd, check=True)
    return out


def embed_tags(master_path, tags: list[str]) -> bool:
    """Best-effort: embed keyword tags into the master via exiftool. No-op if exiftool absent."""
    if not shutil.which("exiftool"):
        return False
    args = ["exiftool", "-overwrite_original"]
    args += [f"-Keywords={t}" for t in tags] if tags else ["-Keywords="]
    args.append(str(master_path))
    subprocess.run(args, check=True, capture_output=True)
    return True
