"""Mirror new masters from the read-only source dir into the writable intake dir.

The source (e.g. the NTFS share clips are recorded into) is read-only: the pipeline
never writes or deletes there. So instead of moving clips out of it, `sync_intake`
*copies* each master into `intake_dir`, where `describe.py`/`ingest.py` operate as usual
(ingest then moves it on into the library).

Because the source is never cleared, a plain mirror would re-copy everything every run and
re-ingest duplicates. So a master is copied only when it is genuinely new -- absent from
both the intake dir (copied, not yet ingested) and the library (already ingested). No state
file: the skip set is just the union of what's already in intake and library.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from clip_core import media


def _library_stems(library_dir: Path) -> set[str]:
    """Stems already ingested (a `<stem>.mp4` master sits in the library)."""
    if not library_dir.is_dir():
        return set()
    return {media.stem_of(p) for p in media.iter_masters(library_dir)}


def sync_intake(cfg, *, dry_run: bool = False, verbose: bool = True) -> list[Path]:
    """Copy new masters from cfg.source_dir into cfg.intake_dir.

    Returns the intake-side paths of the masters copied (or that would be, under dry_run).
    A no-op returning [] when source_dir is unset, missing, or the same dir as intake.
    """
    source = cfg.source_dir
    if source is None:
        return []
    source = Path(source)
    intake = Path(cfg.intake_dir)
    if source == intake:
        return []
    if not source.is_dir():
        if verbose:
            print(f"source dir not found, skipping mirror: {source}")
        return []

    already = _library_stems(Path(cfg.library_dir))
    copied: list[Path] = []
    if not dry_run:
        intake.mkdir(parents=True, exist_ok=True)

    for master in media.iter_masters(source):
        stem = media.stem_of(master)
        dst = intake / master.name
        if stem in already or dst.exists():
            continue  # already ingested, or already staged in intake
        copied.append(dst)
        if dry_run:
            if verbose:
                print(f"[dry-run] would copy {master.name} -> {intake}")
            continue
        shutil.copy2(str(master), str(dst))
        # Bring a sibling _merged rendition along if the source happens to carry one.
        merged_src = master.with_name(media.merged_name_for(master))
        if merged_src.exists():
            merged_dst = intake / merged_src.name
            if not merged_dst.exists():
                shutil.copy2(str(merged_src), str(merged_dst))
        if verbose:
            print(f"copied {master.name} -> {intake}")

    if verbose and copied:
        print(f"mirrored {len(copied)} new master(s) from {source} into {intake}\n")
    return copied
