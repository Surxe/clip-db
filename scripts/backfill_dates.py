#!/usr/bin/env python3
"""Backfill the `date` column on indexed clips using the same resolver as ingest.

Ingest only dates NEW clips, so rows indexed before dating existed (or clips whose
name carried no timestamp) sit with a null date. This walks the index and fills each
null date from media.resolve_date(): a timestamp in the stem, else the container
creation_time tag, else the file mtime.

  python scripts/backfill_dates.py --dry-run   # preview, write nothing
  python scripts/backfill_dates.py             # fill only null dates
  python scripts/backfill_dates.py --all       # also re-derive dates that are already set

A clip whose master file is missing, or that yields no date from any source, is left
untouched.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on sys.path

from clip_core import index, media
from clip_core.config import load_config
from clip_core.schema import connect


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--all", action="store_true", help="re-derive dates even where one is already set")
    args = ap.parse_args()

    cfg = load_config()
    conn = connect(cfg.index_path)

    filled = skipped_have = skipped_nodate = missing = 0
    for clip in index.all_clips(conn):
        if clip.date and not args.all:
            skipped_have += 1
            continue
        if not Path(clip.master_path).exists():
            print(f"  missing master, skipped: {clip.stem} ({clip.master_path})")
            missing += 1
            continue
        date = media.resolve_date(clip.master_path, clip.stem)
        if not date:
            skipped_nodate += 1
            continue
        if date == clip.date:
            continue  # --all re-derive landed on the same value; nothing to write
        action = "would set" if args.dry_run else "set"
        print(f"  {action} {clip.stem}: {clip.date} -> {date}")
        if not args.dry_run:
            index.set_date(conn, clip.stem, date)
        filled += 1

    verb = "would fill" if args.dry_run else "filled"
    print(f"\n{verb} {filled}; already dated {skipped_have}; no date source {skipped_nodate}; missing file {missing}")


if __name__ == "__main__":
    main()
