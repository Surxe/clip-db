#!/usr/bin/env python3
"""Mix a clip's split audio tracks into a _merged.mp4 and attach it to the master's row.

Two modes over the same primitive; output always lands next to the master (in the
library) and is recorded on the asset's index row:

  merge.py CLIP.mp4 [CLIP2.mp4 ...]   # merge the given masters (what the GUI picker calls)
  merge.py --auto                     # merge every indexed master <= threshold seconds
  merge.py --auto --max-seconds 90    # override the threshold (default: CLIP_AUTO_MERGE_MAX_SECONDS)
  merge.py --force ...                # regenerate even if a _merged.mp4 already exists

Both modes are idempotent: an existing merged rendition is skipped unless --force.
Passing a *_merged.mp4 resolves back to its master, so it's harmless.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

import argparse

from clip_core import merge
from clip_core.config import load_config
from clip_core.schema import connect


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="master .mp4 file(s) to merge")
    ap.add_argument("--auto", action="store_true", help="merge every indexed master <= --max-seconds")
    ap.add_argument("--max-seconds", type=int, default=None, help="auto threshold (default from .env, 120)")
    ap.add_argument("--force", action="store_true", help="regenerate even if a _merged.mp4 already exists")
    args = ap.parse_args()

    if args.auto == bool(args.paths):
        ap.error("give file path(s), or --auto -- not both, not neither")

    cfg = load_config()
    conn = connect(cfg.index_path)

    if args.auto:
        max_seconds = args.max_seconds if args.max_seconds is not None else cfg.auto_merge_max_seconds
        results = merge.sweep_short(conn, max_seconds=max_seconds, force=args.force)
        if not results:
            print(f"No masters <= {max_seconds}s need merging.")
            return
    else:
        results = [merge.merge_master(conn, p, force=args.force) for p in args.paths]

    created = skipped = orphaned = 0
    for r in results:
        print(f"[{r.status}] {r.stem} -> {r.merged_path}")
        created += r.status == merge.CREATED
        skipped += r.status == merge.SKIPPED_EXISTS
        orphaned += r.status == merge.NOT_INDEXED

    print(f"\n{created} merged, {skipped} already present, {orphaned} not indexed.")
    if orphaned:
        print("(not-indexed: the merged file was written but its master has no index row -- ingest it first.)")


if __name__ == "__main__":
    main()
