"""Merge orchestration: produce a mixed-audio _merged.mp4 for a master and attach it
to the master's index row.

Layered on top of the pure ffmpeg primitive (`media.regenerate_merged`): this module is
the only place that couples merging to the SQLite index, so `media.py` stays I/O-only.
The merged file is always written next to its master (i.e. in the library) and recorded
on the asset's `stem` row -- never left as a loose, unattached file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import index, media

# status values a merge attempt can end in.
CREATED = "created"            # ffmpeg ran, merged file written + attached
SKIPPED_EXISTS = "skipped"     # a merged rendition already present (idempotent no-op)
NOT_INDEXED = "not-indexed"    # merged file written, but the master has no index row


@dataclass(frozen=True)
class MergeResult:
    stem: str
    status: str
    merged_path: str | None


def merge_master(conn, master_path, *, force: bool = False) -> MergeResult:
    """Mix a single master's audio tracks into its _merged.mp4 and attach it in the index.

    Idempotent: an existing merged file is left untouched unless `force`. If the master
    isn't indexed the merged file is still written, but the result flags `not-indexed`
    so the caller can surface it rather than silently orphaning output.
    """
    master = Path(master_path)
    if media.is_merged(master):  # a _merged file was passed in -> resolve to its master
        master = master.with_name(f"{media.stem_of(master)}{master.suffix}")
    stem = media.stem_of(master)
    out = master.with_name(media.merged_name_for(master))

    if out.exists() and not force:
        return MergeResult(stem, SKIPPED_EXISTS, str(out))

    media.regenerate_merged(master, out)
    attached = index.set_merged_path(conn, stem, str(out))
    return MergeResult(stem, CREATED if attached else NOT_INDEXED, str(out))


def sweep_short(conn, *, max_seconds: int, force: bool = False) -> list[MergeResult]:
    """Merge every indexed master <= max_seconds that has no current merged rendition.

    Idempotent by construction: a clip whose `merged_path` is set and still on disk is
    skipped (unless `force`), so re-running is a clean no-op.
    """
    results: list[MergeResult] = []
    for clip in index.all_clips(conn):
        if clip.duration is None or clip.duration > max_seconds:
            continue
        if not force and clip.merged_path and Path(clip.merged_path).exists():
            continue
        results.append(merge_master(conn, clip.master_path, force=force))
    return results
